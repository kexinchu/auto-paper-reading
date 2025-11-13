"""
内容提取模块
使用OpenAI兼容API提取论文核心内容
支持PDF处理和长度限制
"""

import json
import logging
import os
from typing import Dict, List, Optional
import re
from datetime import datetime
import time
import PyPDF2
import io
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ContentExtractor:
    def __init__(self, model_config: Dict):
        self.model_config = model_config
        
        # OpenAI API配置
        api_key = os.getenv('OPENAI_API_KEY') or model_config.get('api_key', '')
        if not api_key or api_key == 'YOUR_API_KEY_HERE':
            logger.warning("未配置API密钥，请设置环境变量 OPENAI_API_KEY 或在配置文件中设置 api_key")
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=model_config.get('api_base', 'https://api.openai.com/v1'),
            timeout=model_config.get('timeout', 30)
        )
        
        self.model = model_config.get('model', 'gpt-3.5-turbo')
        self.temperature = model_config.get('temperature', 0.1)
        self.max_tokens = model_config.get('max_tokens', 1500)
        self.max_retries = model_config.get('max_retries', 3)
        self.retry_delay = model_config.get('retry_delay', 1)
        
        logger.info("ContentExtractor 初始化成功")
    
    def extract_from_abstract(self, paper: Dict) -> Dict:
        """
        从摘要中提取核心内容
        """
        try:
            title = paper.get('title', '')
            abstract = paper.get('abstract', '')
            authors = ', '.join(paper.get('authors', []))
            
            # 构建提示词
            prompt = f"""请分析以下学术论文的核心内容，并提供简洁的总结：

标题: {title}
作者: {authors}
摘要: {abstract}

请按以下格式回答（用中文）：

1. 研究问题（1-2句话）
2. 核心方法（2-3句话）
3. 主要贡献（2-3句话）
4. 实验结果（1-2句话）

请保持简洁，每部分不超过100字。"""
            
            # 调用LLM
            content = self._call_llm(prompt)
            
            result = {
                'title': title,
                'authors': authors,
                'extracted_content': content if content else '提取失败',
                'source': 'abstract',
                'extraction_time': datetime.now().isoformat(),
                'paper_url': paper.get('pdf_url', paper.get('url', ''))
            }
            
            # 添加原始论文信息
            if 'relevance_score' in paper:
                result['relevance_score'] = paper['relevance_score']
            if 'matched_topic' in paper:
                result['matched_topic'] = paper['matched_topic']
            if 'relevance_reason' in paper:
                result['relevance_reason'] = paper['relevance_reason']
            
            return result
            
        except Exception as e:
            logger.error(f"从摘要提取内容失败: {e}")
            return {
                'title': paper.get('title', 'Unknown'),
                'authors': ', '.join(paper.get('authors', [])),
                'extracted_content': f'提取失败: {str(e)}',
                'source': 'abstract',
                'extraction_time': datetime.now().isoformat(),
                'error': str(e)
            }
    
    def extract_from_pdf(self, pdf_path: str, paper: Dict, max_pages: int = 5) -> Dict:
        """
        从PDF文件提取内容
        """
        try:
            # 读取PDF内容
            pdf_text = self._extract_pdf_text(pdf_path, max_pages)
            
            if not pdf_text or len(pdf_text.strip()) < 100:
                logger.warning(f"PDF文本过短或为空，回退到摘要提取")
                return self.extract_from_abstract(paper)
            
            title = paper.get('title', '')
            authors = ', '.join(paper.get('authors', []))
            
            # 构建提示词（限制PDF文本长度）
            max_text_length = 8000  # 限制上下文长度
            if len(pdf_text) > max_text_length:
                pdf_text = pdf_text[:max_text_length] + "\n...(内容已截断)"
            
            prompt = f"""请分析以下学术论文的核心内容，并提供详细的总结：

标题: {title}
作者: {authors}

论文内容摘录:
{pdf_text}

请按以下格式回答（用中文）：

1. 研究问题（2-3句话）
2. 核心方法（3-4句话）
3. 主要贡献（3-4句话）
4. 实验结果（2-3句话）
5. 创新点（2-3句话）

请保持简洁专业，每部分不超过150字。"""
            
            # 调用LLM
            content = self._call_llm(prompt)
            
            result = {
                'title': title,
                'authors': authors,
                'extracted_content': content if content else '提取失败',
                'source': 'pdf',
                'extraction_time': datetime.now().isoformat(),
                'paper_url': paper.get('pdf_url', paper.get('url', ''))
            }
            
            # 添加原始论文信息
            if 'relevance_score' in paper:
                result['relevance_score'] = paper['relevance_score']
            if 'matched_topic' in paper:
                result['matched_topic'] = paper['matched_topic']
            if 'relevance_reason' in paper:
                result['relevance_reason'] = paper['relevance_reason']
            
            return result
            
        except Exception as e:
            logger.error(f"从PDF提取内容失败: {e}")
            logger.info("回退到从摘要提取")
            return self.extract_from_abstract(paper)
    
    def _extract_pdf_text(self, pdf_path: str, max_pages: int = 5) -> str:
        """
        从PDF提取文本
        """
        try:
            text = ""
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                num_pages = min(len(pdf_reader.pages), max_pages)
                
                for page_num in range(num_pages):
                    page = pdf_reader.pages[page_num]
                    text += page.extract_text() + "\n"
            
            # 清理文本
            text = self._clean_text(text)
            return text
            
        except Exception as e:
            logger.error(f"PDF文本提取失败: {e}")
            return ""
    
    def _clean_text(self, text: str) -> str:
        """
        清理提取的文本
        """
        # 移除多余的空白字符
        text = re.sub(r'\s+', ' ', text)
        # 移除特殊字符
        text = re.sub(r'[^\w\s\.,;:!?()-]', '', text)
        return text.strip()
    
    def _call_llm(self, prompt: str, max_retries: int = None) -> str:
        """
        调用LLM API（OpenAI兼容接口）
        """
        if max_retries is None:
            max_retries = self.max_retries
            
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是一个专业的学术论文分析助手，擅长提取和总结论文的核心内容。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens
                )
                
                return response.choices[0].message.content.strip()
                    
            except Exception as e:
                logger.warning(f"LLM API调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(self.retry_delay)
                    
        return ""
    
    def batch_extract(self, papers: List[Dict], from_pdf: bool = False) -> List[Dict]:
        """
        批量提取论文内容
        """
        results = []
        for i, paper in enumerate(papers):
            logger.info(f"提取第 {i+1}/{len(papers)} 篇论文内容")
            
            if from_pdf and 'pdf_path' in paper:
                result = self.extract_from_pdf(paper['pdf_path'], paper)
            else:
                result = self.extract_from_abstract(paper)
            
            results.append(result)
            
            # 添加延迟避免API限流
            if i < len(papers) - 1:
                time.sleep(1)
        
        return results
    
    def test_connection(self) -> bool:
        """
        测试API连接
        """
        try:
            test_prompt = "请回答: 1+1等于多少？"
            response = self._call_llm(test_prompt)
            if response:
                logger.info("LLM API连接测试成功")
                return True
            else:
                logger.error("LLM API连接测试失败: 无响应")
                return False
        except Exception as e:
            logger.error(f"LLM API连接测试失败: {e}")
            return False


def test_extractor():
    """测试内容提取器"""
    # 从环境变量或配置文件加载配置
    try:
        import yaml
        with open('config.yaml', 'r', encoding='utf-8') as f:
            full_config = yaml.safe_load(f)
            config = full_config.get('llm', {})
    except:
        config = {
            'api_base': os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1'),
            'api_key': os.getenv('OPENAI_API_KEY', ''),
            'model': os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo'),
            'max_retries': 3,
            'retry_delay': 1
        }
    
    extractor = ContentExtractor(config)
    
    # 测试连接
    if not extractor.test_connection():
        print("❌ API连接测试失败")
        return
    
    print("✅ API连接测试成功")
    
    # 测试内容提取
    test_paper = {
        'title': 'Attention Is All You Need',
        'abstract': 'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...',
        'authors': ['Ashish Vaswani', 'Noam Shazeer']
    }
    
    result = extractor.extract_from_abstract(test_paper)
    print(f"\n提取结果:")
    print(f"标题: {result['title']}")
    print(f"内容: {result['extracted_content']}")


if __name__ == "__main__":
    test_extractor()
