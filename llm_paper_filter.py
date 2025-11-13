"""
基于LLM的智能论文筛选模块
使用主题描述和LLM判断论文相关性
支持OpenAI兼容API（OpenAI、DeepSeek、SiliconFlow、Qwen等）

筛选流程：
1. 关键词预筛选：快速过滤明显不相关的论文
2. LLM相关性评估：判断论文与主题的相关程度（0-10分）
3. LLM质量评估：判断论文的学术质量和创新性（0-10分）
4. 综合评分：根据相关性和质量的加权得分决定是否保留
"""

import yaml
import os
from typing import List, Dict, Tuple, Set
import logging
from datetime import datetime
from openai import OpenAI
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMPaperFilter:
    def __init__(self, config: Dict):
        self.config = config
        
        # 从环境变量或配置获取API密钥
        api_key = os.getenv('OPENAI_API_KEY') or config.get('api_key', '')
        if not api_key or api_key == 'YOUR_API_KEY_HERE':
            logger.warning("未配置API密钥，请设置环境变量 OPENAI_API_KEY 或在配置文件中设置 api_key")
        
        # 初始化OpenAI客户端（支持兼容接口）
        self.client = OpenAI(
            api_key=api_key,
            base_url=config.get('api_base', 'https://api.openai.com/v1'),
            timeout=config.get('timeout', 30)
        )
        
        self.model = config.get('model', 'gpt-3.5-turbo')
        self.temperature = config.get('temperature', 0.1)
        self.max_tokens = config.get('max_tokens', 500)
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 1)
        
        # 加载主题配置
        topics_data = self._load_topics()
        self.topics = topics_data.get('topics', [])
        self.filtering_config = topics_data.get('filtering', {})
        
        # 筛选参数
        self.keyword_threshold = self.filtering_config.get('keyword_match_threshold', 0.1)
        self.min_relevance_score = self.filtering_config.get('min_relevance_score', 6)
        self.min_quality_score = self.filtering_config.get('min_quality_score', 6)
        self.relevance_weight = self.filtering_config.get('relevance_weight', 0.6)
        self.quality_weight = self.filtering_config.get('quality_weight', 0.4)
        self.min_combined_score = self.filtering_config.get('min_combined_score', 6.0)
        self.enable_quality = self.filtering_config.get('enable_quality_assessment', True)
        
        logger.info(f"筛选配置: 关键词阈值={self.keyword_threshold}, "
                   f"相关性阈值={self.min_relevance_score}, "
                   f"质量阈值={self.min_quality_score}, "
                   f"综合评分阈值={self.min_combined_score}")
        
    def _load_topics(self) -> Dict:
        """加载主题配置"""
        try:
            with open('topics.yaml', 'r', encoding='utf-8') as f:
                topics_config = yaml.safe_load(f)
            return topics_config
        except Exception as e:
            logger.error(f"加载主题文件失败: {e}")
            return {'topics': [], 'filtering': {}}
    
    def _extract_keywords_from_paper(self, paper: Dict) -> Set[str]:
        """从论文标题和摘要中提取关键词（转为小写）"""
        text = (paper.get('title', '') + ' ' + paper.get('abstract', '')).lower()
        # 简单的词提取（可以使用更复杂的NLP方法）
        words = set(re.findall(r'\b\w+\b', text))
        return words
    
    def _calculate_keyword_match(self, paper: Dict, topic: Dict) -> Tuple[float, List[str]]:
        """
        计算关键词匹配度
        返回：(匹配比例, 匹配到的关键词列表)
        """
        keywords = topic.get('keywords', [])
        required_keywords = topic.get('required_keywords', [])
        
        if not keywords:
            return 1.0, []  # 如果没有配置关键词，则跳过关键词筛选
        
        paper_words = self._extract_keywords_from_paper(paper)
        
        # 检查必需关键词
        if required_keywords:
            required_found = False
            for req_kw in required_keywords:
                if req_kw.lower() in paper_words or any(req_kw.lower() in word for word in paper_words):
                    required_found = True
                    break
            if not required_found:
                return 0.0, []
        
        # 计算匹配的关键词
        matched_keywords = []
        for keyword in keywords:
            keyword_lower = keyword.lower()
            # 完全匹配或部分匹配
            if keyword_lower in paper_words or any(keyword_lower in word for word in paper_words):
                matched_keywords.append(keyword)
        
        match_ratio = len(matched_keywords) / len(keywords) if keywords else 0
        return match_ratio, matched_keywords
    
    def _call_llm(self, prompt: str, max_retries: int = None) -> str:
        """调用LLM API（OpenAI兼容接口）"""
        if max_retries is None:
            max_retries = self.max_retries
            
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "你是一个专业的学术论文评估助手，能够准确判断论文的相关性和质量。"},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens
                )
                
                return response.choices[0].message.content.strip()
                    
            except Exception as e:
                logger.warning(f"LLM API调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(self.retry_delay)
                    
        return ""
    
    def _create_relevance_prompt(self, paper: Dict, topic: Dict) -> str:
        """创建相关性评估提示"""
        topic_name = topic['name']
        topic_description = topic['description']
        
        prompt = f"""请评估以下论文是否与主题"{topic_name}"相关。

主题描述: {topic_description}

论文信息:
标题: {paper['title']}
摘要: {paper['abstract'][:1500]}

请按以下格式回答:
相关性评分: [0-10的整数，10表示高度相关，0表示完全不相关]
理由: [简要说明评分理由，1-2句话]

评分标准：
- 9-10分: 直接解决该主题的核心问题
- 7-8分: 与主题密切相关
- 5-6分: 与主题有一定相关性
- 3-4分: 略微相关
- 0-2分: 基本不相关

只返回评分和理由，不要其他内容。"""
        return prompt
    
    def _create_quality_prompt(self, paper: Dict) -> str:
        """创建质量评估提示"""
        prompt = f"""请评估以下论文的学术质量和创新性，并判断是否需要阅读全文。

论文信息:
标题: {paper['title']}
摘要: {paper['abstract'][:1500]}

请按以下格式回答:
质量评分: [0-10的整数，10表示质量极高，0表示质量很差]
需要全文: [是/否]
理由: [简要说明评分理由和是否需要全文的原因，2-3句话]

评分标准：
- 9-10分: 重大突破性研究，方法新颖，实验充分，影响力大
- 7-8分: 创新性强，方法可靠，实验充分
- 5-6分: 有一定创新，方法合理，实验基本充分
- 3-4分: 创新性一般，方法常规，实验不够充分
- 0-2分: 缺乏创新，方法陈旧，或实验不足

是否需要全文标准：
- 需要全文：摘要信息不足以理解核心方法，或者技术细节需要深入了解
- 不需要：摘要已经清楚说明了方法和结果，或者论文质量/相关性一般

评估要点：
1. 创新性：是否提出新方法、新思路？
2. 方法可靠性：方法是否科学严谨？
3. 实验充分性：实验是否全面、对比是否充分？
4. 实际价值：解决的问题是否重要？
5. 摘要完整性：摘要是否已经包含足够信息？

只返回评分、是否需要全文和理由，不要其他内容。"""
        return prompt
    
    def _parse_llm_response(self, response: str, score_prefix: str = '相关性评分') -> Tuple[int, str]:
        """解析LLM响应（相关性评估）"""
        try:
            lines = response.strip().split('\n')
            score = 0
            reason = ""
            
            for line in lines:
                if score_prefix in line or '评分' in line:
                    score_text = line.split(':', 1)[-1].strip()
                    # 提取数字
                    numbers = re.findall(r'\d+', score_text)
                    if numbers:
                        score = int(numbers[0])
                        score = max(0, min(10, score))  # 限制在0-10范围
                elif '理由' in line or 'reason' in line.lower():
                    reason = line.split(':', 1)[-1].strip()
            
            return score, reason
        except Exception as e:
            logger.warning(f"解析LLM响应失败: {e}")
            return 0, "解析失败"
    
    def _parse_quality_response(self, response: str) -> Tuple[int, bool, str]:
        """
        解析质量评估响应
        返回：(质量评分, 是否需要全文, 理由)
        """
        try:
            lines = response.strip().split('\n')
            score = 0
            need_fulltext = False
            reason = ""
            
            for line in lines:
                if '质量评分' in line or '评分' in line:
                    score_text = line.split(':', 1)[-1].strip()
                    numbers = re.findall(r'\d+', score_text)
                    if numbers:
                        score = int(numbers[0])
                        score = max(0, min(10, score))
                elif '需要全文' in line or 'fulltext' in line.lower():
                    text = line.split(':', 1)[-1].strip().lower()
                    # 判断是否需要全文
                    need_fulltext = ('是' in text or 'yes' in text or '需要' in text or 'true' in text)
                elif '理由' in line:
                    reason = line.split(':', 1)[-1].strip()
            
            return score, need_fulltext, reason
        except Exception as e:
            logger.warning(f"解析质量评估响应失败: {e}")
            return 0, False, "解析失败"
    
    def _evaluate_paper(self, paper: Dict, topic: Dict) -> Dict:
        """
        评估单篇论文
        返回：评估结果字典
        """
        result = {
            'relevance_score': 0,
            'relevance_reason': '',
            'quality_score': 0,
            'quality_reason': '',
            'combined_score': 0,
            'matched_keywords': [],
            'keyword_match_ratio': 0,
            'need_fulltext': False,  # 是否需要下载全文
            'passed': False
        }
        
        # 1. 关键词筛选
        match_ratio, matched_kws = self._calculate_keyword_match(paper, topic)
        result['keyword_match_ratio'] = match_ratio
        result['matched_keywords'] = matched_kws
        
        logger.info(f"  关键词匹配: {match_ratio:.2%} ({len(matched_kws)}/{len(topic.get('keywords', []))})")
        
        if match_ratio < self.keyword_threshold:
            logger.info(f"  关键词匹配度过低，跳过LLM评估")
            return result
        
        # 2. LLM相关性评估
        relevance_prompt = self._create_relevance_prompt(paper, topic)
        relevance_response = self._call_llm(relevance_prompt)
        
        if relevance_response:
            rel_score, rel_reason = self._parse_llm_response(relevance_response, '相关性评分')
            result['relevance_score'] = rel_score
            result['relevance_reason'] = rel_reason
            logger.info(f"  相关性评分: {rel_score}/10")
        else:
            logger.warning("  LLM相关性评估失败")
            return result
        
        # 3. LLM质量评估（如果启用）
        if self.enable_quality and result['relevance_score'] >= self.min_relevance_score:
            quality_prompt = self._create_quality_prompt(paper)
            quality_response = self._call_llm(quality_prompt)
            
            if quality_response:
                qual_score, need_fulltext, qual_reason = self._parse_quality_response(quality_response)
                result['quality_score'] = qual_score
                result['quality_reason'] = qual_reason
                result['need_fulltext'] = need_fulltext
                logger.info(f"  质量评分: {qual_score}/10, 需要全文: {'是' if need_fulltext else '否'}")
            else:
                logger.warning("  LLM质量评估失败")
                result['quality_score'] = self.min_quality_score  # 默认及格分
                result['need_fulltext'] = False  # 默认不需要全文
        else:
            result['quality_score'] = 10  # 如果不评估质量，给满分
            result['need_fulltext'] = False  # 默认不需要全文
        
        # 4. 计算综合评分
        combined_score = (result['relevance_score'] * self.relevance_weight + 
                         result['quality_score'] * self.quality_weight)
        result['combined_score'] = combined_score
        
        # 5. 判断是否通过
        passed = (result['relevance_score'] >= self.min_relevance_score and
                 result['quality_score'] >= self.min_quality_score and
                 combined_score >= self.min_combined_score)
        result['passed'] = passed
        
        logger.info(f"  综合评分: {combined_score:.1f}/10, 通过: {passed}")
        
        return result
    
    def filter_papers(self, papers: List[Dict]) -> List[Dict]:
        """
        使用关键词+LLM筛选相关论文
        """
        if not papers:
            return []
            
        if not self.topics:
            logger.warning("没有配置主题，返回所有论文")
            return papers
        
        filtered_papers = []
        
        for i, paper in enumerate(papers):
            logger.info(f"\n正在评估论文 {i+1}/{len(papers)}: {paper['title'][:60]}...")
            
            best_result = None
            best_topic = None
            
            # 对每个主题进行评估
            for topic in self.topics:
                logger.info(f"评估主题: {topic['name']}")
                result = self._evaluate_paper(paper, topic)
                
                if result['passed'] and (best_result is None or 
                                        result['combined_score'] > best_result['combined_score']):
                    best_result = result
                    best_topic = topic['name']
            
            # 如果通过筛选，则保留论文
            if best_result and best_result['passed']:
                paper_copy = paper.copy()
                paper_copy['relevance_score'] = best_result['relevance_score']
                paper_copy['relevance_reason'] = best_result['relevance_reason']
                paper_copy['quality_score'] = best_result['quality_score']
                paper_copy['quality_reason'] = best_result['quality_reason']
                paper_copy['combined_score'] = best_result['combined_score']
                paper_copy['matched_topic'] = best_topic
                paper_copy['matched_keywords'] = best_result['matched_keywords']
                paper_copy['keyword_match_ratio'] = best_result['keyword_match_ratio']
                paper_copy['need_fulltext'] = best_result['need_fulltext']  # 是否需要下载全文
                
                filtered_papers.append(paper_copy)
                fulltext_mark = "📄 需要全文" if best_result['need_fulltext'] else "📋 仅摘要"
                logger.info(f"✅ 论文通过筛选 (相关性: {best_result['relevance_score']}, "
                          f"质量: {best_result['quality_score']}, "
                          f"综合: {best_result['combined_score']:.1f}, "
                          f"{fulltext_mark}, "
                          f"主题: {best_topic})")
            else:
                logger.info(f"❌ 论文未通过筛选")
        
        logger.info(f"\n筛选完成: {len(filtered_papers)}/{len(papers)} 篇论文通过筛选")
        
        # 按综合评分排序
        filtered_papers.sort(key=lambda x: x.get('combined_score', 0), reverse=True)
        
        return filtered_papers
    
    def test_llm_connection(self) -> bool:
        """测试LLM连接"""
        try:
            test_prompt = "请回答: 1+1等于多少？只需回答数字。"
            response = self._call_llm(test_prompt)
            if response:
                logger.info(f"LLM连接测试成功，响应: {response}")
                return True
            else:
                logger.error("LLM连接测试失败: 无响应")
                return False
        except Exception as e:
            logger.error(f"LLM连接测试失败: {e}")
            return False


def test_llm_filter():
    """测试LLM筛选功能"""
    # 从环境变量或配置文件加载配置
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            import yaml
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
    
    filter_obj = LLMPaperFilter(config)
    
    # 测试连接
    if not filter_obj.test_llm_connection():
        print("❌ LLM连接测试失败")
        return
    
    print("✅ LLM连接测试成功")
    
    # 测试论文筛选
    test_papers = [
        {
            'title': 'Efficient KV-Cache Optimization for Large Language Models',
            'abstract': 'This paper presents a novel approach to optimize the key-value cache in transformer-based large language models, significantly reducing memory usage while maintaining performance. We propose a dynamic cache management strategy that adaptively selects which tokens to keep in the cache.',
            'authors': ['John Doe', 'Jane Smith']
        },
        {
            'title': 'A Study of Butterfly Migration Patterns',
            'abstract': 'We analyze the migration patterns of monarch butterflies across North America, focusing on environmental factors that influence their journey. Our findings suggest that climate change is affecting traditional migration routes.',
            'authors': ['Alice Johnson']
        }
    ]
    
    filtered_papers = filter_obj.filter_papers(test_papers)
    print(f"\n筛选结果: {len(filtered_papers)}/{len(test_papers)} 篇论文通过筛选\n")
    
    for paper in filtered_papers:
        print(f"标题: {paper['title']}")
        print(f"主题: {paper['matched_topic']}")
        print(f"相关性: {paper['relevance_score']}/10 - {paper['relevance_reason']}")
        if 'quality_score' in paper and paper['quality_score'] > 0:
            print(f"质量: {paper['quality_score']}/10 - {paper['quality_reason']}")
        print(f"综合评分: {paper['combined_score']:.1f}/10")
        print(f"匹配关键词: {', '.join(paper['matched_keywords'])}")
        print()


if __name__ == "__main__":
    test_llm_filter()
