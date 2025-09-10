"""
基于LLM的智能论文筛选模块
使用主题描述和LLM判断论文相关性
"""

import yaml
import requests
import json
from typing import List, Dict, Tuple
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LLMPaperFilter:
    def __init__(self, config: Dict):
        self.config = config
        self.sglang_server_url = config.get('sglang_server_url', 'http://localhost:30000')
        self.topics = self._load_topics()
        self.max_retries = config.get('max_retries', 3)
        self.retry_delay = config.get('retry_delay', 1)
        
    def _load_topics(self) -> List[Dict]:
        """加载主题配置"""
        try:
            with open('topics.yaml', 'r', encoding='utf-8') as f:
                topics_config = yaml.safe_load(f)
            return topics_config.get('topics', [])
        except Exception as e:
            logger.error(f"加载主题文件失败: {e}")
            return []
    
    def _call_llm(self, prompt: str, max_retries: int = None) -> str:
        """调用LLM API"""
        if max_retries is None:
            max_retries = self.max_retries
            
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    f"{self.sglang_server_url}/v1/chat/completions",
                    json={
                        "model": "default",
                        "messages": [
                            {"role": "system", "content": "你是一个专业的学术论文筛选助手，能够准确判断论文与给定主题的相关性。"},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 200
                    },
                    timeout=30
                )
                
                if response.status_code == 200:
                    result = response.json()
                    return result['choices'][0]['message']['content'].strip()
                else:
                    logger.warning(f"LLM API调用失败，状态码: {response.status_code}")
                    
            except Exception as e:
                logger.warning(f"LLM API调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(self.retry_delay)
                    
        return ""
    
    def _create_evaluation_prompt(self, paper: Dict, topic: Dict) -> str:
        """创建论文评估提示"""
        topic_name = topic['name']
        topic_description = topic['description']
        
        prompt = f"""
请评估以下论文是否与主题"{topic_name}"相关。

主题描述: {topic_description}

论文信息:
标题: {paper['title']}
摘要: {paper['abstract'][:1000]}...

请按以下格式回答:
相关性评分: [0-10的整数，10表示高度相关，0表示完全不相关]
理由: [简要说明评分的理由，1-2句话]

只返回评分和理由，不要其他内容。
"""
        return prompt
    
    def _parse_llm_response(self, response: str) -> Tuple[int, str]:
        """解析LLM响应"""
        try:
            lines = response.strip().split('\n')
            score = 0
            reason = ""
            
            for line in lines:
                if line.startswith('相关性评分:'):
                    score_text = line.split(':')[1].strip()
                    # 提取数字
                    import re
                    numbers = re.findall(r'\d+', score_text)
                    if numbers:
                        score = int(numbers[0])
                elif line.startswith('理由:'):
                    reason = line.split(':', 1)[1].strip()
            
            return score, reason
        except Exception as e:
            logger.warning(f"解析LLM响应失败: {e}")
            return 0, "解析失败"
    
    def filter_papers(self, papers: List[Dict], min_score: int = 6) -> List[Dict]:
        """
        使用LLM筛选相关论文
        """
        if not papers:
            return []
            
        if not self.topics:
            logger.warning("没有配置主题，返回所有论文")
            return papers
            
        filtered_papers = []
        
        for i, paper in enumerate(papers):
            logger.info(f"正在评估论文 {i+1}/{len(papers)}: {paper['title'][:50]}...")
            
            best_score = 0
            best_reason = ""
            best_topic = None
            
            # 对每个主题进行评估
            for topic in self.topics:
                prompt = self._create_evaluation_prompt(paper, topic)
                response = self._call_llm(prompt)
                
                if response:
                    score, reason = self._parse_llm_response(response)
                    if score > best_score:
                        best_score = score
                        best_reason = reason
                        best_topic = topic['name']
            
            # 如果最高分数达到阈值，则保留论文
            if best_score >= min_score:
                paper_copy = paper.copy()
                paper_copy['relevance_score'] = best_score
                paper_copy['relevance_reason'] = best_reason
                paper_copy['matched_topic'] = best_topic
                filtered_papers.append(paper_copy)
                logger.info(f"论文通过筛选 (评分: {best_score}, 主题: {best_topic})")
            else:
                logger.info(f"论文未通过筛选 (最高评分: {best_score})")
        
        logger.info(f"筛选完成: {len(filtered_papers)}/{len(papers)} 篇论文通过筛选")
        return filtered_papers
    
    def test_llm_connection(self) -> bool:
        """测试LLM连接"""
        try:
            test_prompt = "请回答: 1+1等于多少？"
            response = self._call_llm(test_prompt)
            if response:
                logger.info("LLM连接测试成功")
                return True
            else:
                logger.error("LLM连接测试失败: 无响应")
                return False
        except Exception as e:
            logger.error(f"LLM连接测试失败: {e}")
            return False


def test_llm_filter():
    """测试LLM筛选功能"""
    config = {
        'sglang_server_url': 'http://localhost:30000',
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
            'abstract': 'This paper presents a novel approach to optimize the key-value cache in transformer-based large language models, significantly reducing memory usage while maintaining performance.',
            'authors': ['John Doe', 'Jane Smith']
        },
        {
            'title': 'A Study of Butterfly Migration Patterns',
            'abstract': 'We analyze the migration patterns of monarch butterflies across North America, focusing on environmental factors that influence their journey.',
            'authors': ['Alice Johnson']
        }
    ]
    
    filtered_papers = filter_obj.filter_papers(test_papers, min_score=5)
    print(f"筛选结果: {len(filtered_papers)}/{len(test_papers)} 篇论文通过筛选")
    
    for paper in filtered_papers:
        print(f"- {paper['title']}")
        print(f"  评分: {paper['relevance_score']}, 主题: {paper['matched_topic']}")
        print(f"  理由: {paper['relevance_reason']}")


if __name__ == "__main__":
    test_llm_filter()
