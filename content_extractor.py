"""
内容提取模块
使用SGLang API调用Qwen模型提取论文核心内容
支持PDF处理和长度限制
"""

import requests
import json
import logging
import os
from typing import Dict, List, Optional
import re
from datetime import datetime
import time
import PyPDF2
import io

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ContentExtractor:
    def __init__(self, model_config: Dict):
        self.model_config = model_config
        self.sglang_server_url = model_config.get('sglang_server_url', 'http://localhost:8089')
        self.max_context_length = model_config.get('max_context_length', 32768)
        self.max_generation_length = model_config.get('max_generation_length', 2048)
        self.temperature = model_config.get('temperature', 0.7)
        self.max_retries = model_config.get('max_retries', 3)
        self.retry_delay = model_config.get('retry_delay', 1)
        self.download_from_huggingface = model_config.get('download_from_huggingface', True)
        
        self._check_server_health()
    
    def _check_server_health(self):
        """检查SGLang服务器健康状态"""
        try:
            response = requests.get(f"{self.sglang_server_url}/health", timeout=10)
            if response.status_code == 200:
                logger.info("SGLang服务器连接正常")
            else:
                logger.warning(f"SGLang服务器响应异常: {response.status_code}")
        except Exception as e:
            logger.error(f"无法连接到SGLang服务器: {e}")
            logger.info("请确保SGLang服务器正在运行")
    
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

请从以下几个方面进行分析：
1. 研究问题：这篇论文要解决什么问题？
2. 主要方法：使用了什么技术或方法？
3. 关键创新：有什么新颖的贡献？
4. 实验结果：主要结果是什么？
5. 实际意义：对领域有什么影响？

请用中文回答，保持简洁明了："""

            # 生成回答
            response = self._generate_response(prompt)
            
            return {
                'title': title,
                'authors': authors,
                'extracted_content': response,
                'extraction_time': datetime.now().isoformat(),
                'source': 'abstract'
            }
            
        except Exception as e:
            logger.error(f"从摘要提取内容失败: {e}")
            return {
                'title': paper.get('title', ''),
                'authors': ', '.join(paper.get('authors', [])),
                'extracted_content': f"内容提取失败: {str(e)}",
                'extraction_time': datetime.now().isoformat(),
                'source': 'abstract'
            }
    
    def extract_from_pdf(self, pdf_path: str, paper: Dict, max_pages: int = 5) -> Dict:
        """
        从PDF中提取核心内容
        """
        try:
            if not os.path.exists(pdf_path):
                logger.warning(f"PDF文件不存在: {pdf_path}")
                return self.extract_from_abstract(paper)
            
            # 提取PDF文本
            pdf_text = self._extract_pdf_text(pdf_path, max_pages)
            
            if not pdf_text:
                logger.warning("PDF文本提取失败，使用摘要")
                return self.extract_from_abstract(paper)
            
            # 检查文本长度
            if len(pdf_text) > self.max_context_length * 4:  # 粗略估计token数量
                logger.warning("PDF文本过长，截取前部分内容")
                pdf_text = pdf_text[:self.max_context_length * 4]
            
            title = paper.get('title', '')
            authors = ', '.join(paper.get('authors', []))
            
            # 构建提示词
            prompt = f"""请分析以下学术论文的核心内容，并提供简洁的总结：

标题: {title}
作者: {authors}
论文内容: {pdf_text}

请从以下几个方面进行分析：
1. 研究问题：这篇论文要解决什么问题？
2. 主要方法：使用了什么技术或方法？
3. 关键创新：有什么新颖的贡献？
4. 实验结果：主要结果是什么？
5. 实际意义：对领域有什么影响？

请用中文回答，保持简洁明了："""

            # 生成回答
            response = self._generate_response(prompt)
            
            return {
                'title': title,
                'authors': authors,
                'extracted_content': response,
                'extraction_time': datetime.now().isoformat(),
                'source': 'pdf'
            }
            
        except Exception as e:
            logger.error(f"从PDF提取内容失败: {e}")
            return self.extract_from_abstract(paper)
    
    def _extract_pdf_text(self, pdf_path: str, max_pages: int = 5) -> str:
        """
        从PDF文件中提取文本
        """
        try:
            text = ""
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                # 限制提取页数
                pages_to_extract = min(len(pdf_reader.pages), max_pages)
                
                for page_num in range(pages_to_extract):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    text += page_text + "\n"
                    
            return text.strip()
            
        except Exception as e:
            logger.error(f"PDF文本提取失败: {e}")
            return ""
    
    def _generate_response(self, prompt: str) -> str:
        """
        使用SGLang API生成回答
        """
        for attempt in range(self.max_retries):
            try:
                # 构建请求数据
                data = {
                    "model": "default",
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    "temperature": self.temperature,
                    "max_tokens": self.max_generation_length,
                    "stream": False
                }
                
                # 发送请求
                response = requests.post(
                    f"{self.sglang_server_url}/v1/chat/completions",
                    json=data,
                    headers={"Content-Type": "application/json"},
                    timeout=60
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0]["message"]["content"]
                        return content.strip()
                    else:
                        logger.error(f"API响应格式异常: {result}")
                        return "API响应格式异常"
                else:
                    logger.error(f"API请求失败: {response.status_code} - {response.text}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (2 ** attempt))  # 指数退避
                        continue
                    return f"API请求失败: {response.status_code}"
                    
            except requests.exceptions.Timeout:
                logger.error(f"请求超时 (尝试 {attempt + 1}/{self.max_retries})")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                    continue
                return "请求超时"
                
            except Exception as e:
                logger.error(f"生成回答失败 (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                    continue
                return f"生成回答时出错: {str(e)}"
        
        return "所有重试尝试都失败了"
    
    def batch_extract(self, papers: List[Dict], auto_delete_pdf: bool = True) -> List[Dict]:
        """
        批量提取内容
        """
        results = []
        
        for i, paper in enumerate(papers):
            logger.info(f"正在处理第 {i+1}/{len(papers)} 篇论文: {paper.get('title', '')[:50]}...")
            
            # 检查是否有PDF文件
            pdf_path = paper.get('pdf_path')
            if pdf_path and os.path.exists(pdf_path):
                result = self.extract_from_pdf(pdf_path, paper)
                
                # 自动删除PDF文件
                if auto_delete_pdf:
                    try:
                        os.remove(pdf_path)
                        logger.info(f"PDF文件已删除: {pdf_path}")
                    except Exception as e:
                        logger.error(f"删除PDF文件失败: {e}")
            else:
                result = self.extract_from_abstract(paper)
            
            results.append(result)
        
        return results
    
    def format_for_email(self, extracted_contents: List[Dict]) -> str:
        """
        格式化内容用于邮件发送
        """
        if not extracted_contents:
            return "今天没有找到相关的论文。"
        
        email_content = f"# 今日论文摘要 ({datetime.now().strftime('%Y-%m-%d')})\n\n"
        email_content += f"共找到 {len(extracted_contents)} 篇相关论文：\n\n"
        
        for i, content in enumerate(extracted_contents, 1):
            email_content += f"## {i}. {content['title']}\n\n"
            email_content += f"**作者**: {content['authors']}\n\n"
            email_content += f"**核心内容**:\n{content['extracted_content']}\n\n"
            email_content += "---\n\n"
        
        return email_content


def test_content_extractor():
    """
    测试内容提取功能
    """
    # 测试配置
    model_config = {
        'sglang_server_url': 'http://localhost:8089',
        'max_length': 1024,
        'temperature': 0.7,
        'max_retries': 3,
        'retry_delay': 1
    }
    
    # 测试论文数据
    test_paper = {
        'title': 'Attention Is All You Need',
        'abstract': 'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks that include an encoder and a decoder. The best performing models also connect the encoder and decoder through an attention mechanism. We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with recurrence and convolutions entirely.',
        'authors': ['Ashish Vaswani', 'Noam Shazeer', 'Niki Parmar']
    }
    
    try:
        extractor = ContentExtractor(model_config)
        result = extractor.extract_from_abstract(test_paper)
        
        print("提取结果:")
        print(f"标题: {result['title']}")
        print(f"作者: {result['authors']}")
        print(f"内容: {result['extracted_content']}")
        
    except Exception as e:
        print(f"测试失败: {e}")


if __name__ == "__main__":
    test_content_extractor()
