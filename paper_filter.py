"""
论文筛选模块
根据关键词筛选相关论文
"""

import yaml
import re
from typing import List, Dict, Tuple
from sentence_transformers import SentenceTransformer
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PaperFilter:
    def __init__(self, keywords_file: str = "keywords.yaml"):
        self.keywords_file = keywords_file
        self.keywords_config = self._load_keywords()
        self.sentence_model = None
        self._init_sentence_model()
        
    def _load_keywords(self) -> Dict:
        """加载关键词配置"""
        try:
            with open(self.keywords_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"加载关键词文件失败: {e}")
            return {}
    
    def _init_sentence_model(self):
        """初始化句子嵌入模型"""
        try:
            # 使用轻量级的句子嵌入模型
            self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2')
            logger.info("句子嵌入模型加载成功")
        except Exception as e:
            logger.error(f"加载句子嵌入模型失败: {e}")
            self.sentence_model = None
    
    def _extract_keywords(self) -> List[str]:
        """从配置中提取所有关键词"""
        keywords = []
        if 'keywords' in self.keywords_config:
            for category, words in self.keywords_config['keywords'].items():
                keywords.extend(words)
        return keywords
    
    def exact_match(self, text: str, keywords: List[str]) -> Tuple[bool, float, List[str]]:
        """
        精确匹配
        """
        text_lower = text.lower()
        matched_keywords = []
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            if keyword_lower in text_lower:
                matched_keywords.append(keyword)
        
        score = len(matched_keywords) / len(keywords) if keywords else 0
        return len(matched_keywords) > 0, score, matched_keywords
    
    def fuzzy_match(self, text: str, keywords: List[str]) -> Tuple[bool, float, List[str]]:
        """
        模糊匹配（基于正则表达式）
        """
        text_lower = text.lower()
        matched_keywords = []
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            # 将关键词转换为正则表达式，允许部分匹配
            pattern = re.escape(keyword_lower).replace(r'\ ', r'\s+')
            if re.search(pattern, text_lower):
                matched_keywords.append(keyword)
        
        score = len(matched_keywords) / len(keywords) if keywords else 0
        return len(matched_keywords) > 0, score, matched_keywords
    
    def semantic_match(self, text: str, keywords: List[str]) -> Tuple[bool, float, List[str]]:
        """
        语义匹配
        """
        if not self.sentence_model:
            logger.warning("句子嵌入模型未加载，回退到精确匹配")
            return self.exact_match(text, keywords)
        
        try:
            # 计算文本和关键词的嵌入
            text_embedding = self.sentence_model.encode([text])
            keyword_embeddings = self.sentence_model.encode(keywords)
            
            # 计算相似度
            similarities = cosine_similarity(text_embedding, keyword_embeddings)[0]
            
            # 获取匹配的关键词
            threshold = self.keywords_config.get('matching', {}).get('threshold', 0.7)
            matched_indices = np.where(similarities >= threshold)[0]
            matched_keywords = [keywords[i] for i in matched_indices]
            
            # 计算平均相似度作为分数
            score = np.mean(similarities[matched_indices]) if len(matched_indices) > 0 else 0
            
            return len(matched_keywords) > 0, score, matched_keywords
            
        except Exception as e:
            logger.error(f"语义匹配失败: {e}")
            return self.exact_match(text, keywords)
    
    def filter_papers(self, papers: List[Dict]) -> List[Dict]:
        """
        筛选论文
        """
        keywords = self._extract_keywords()
        if not keywords:
            logger.warning("没有找到关键词，返回所有论文")
            return papers
        
        matching_config = self.keywords_config.get('matching', {})
        mode = matching_config.get('mode', 'semantic')
        min_score = self.keywords_config.get('filtering', {}).get('min_score', 0.3)
        
        filtered_papers = []
        
        for paper in papers:
            # 组合标题和摘要进行匹配
            text = f"{paper['title']} {paper['abstract']}"
            
            # 根据模式选择匹配方法
            if mode == 'exact':
                is_match, score, matched_keywords = self.exact_match(text, keywords)
            elif mode == 'fuzzy':
                is_match, score, matched_keywords = self.fuzzy_match(text, keywords)
            else:  # semantic
                is_match, score, matched_keywords = self.semantic_match(text, keywords)
            
            if is_match and score >= min_score:
                paper['match_score'] = score
                paper['matched_keywords'] = matched_keywords
                filtered_papers.append(paper)
                logger.info(f"论文匹配: {paper['title'][:50]}... (分数: {score:.3f})")
        
        # 按匹配分数排序
        filtered_papers.sort(key=lambda x: x['match_score'], reverse=True)
        
        # 限制数量
        max_papers = self.keywords_config.get('filtering', {}).get('max_papers', 10)
        if len(filtered_papers) > max_papers:
            filtered_papers = filtered_papers[:max_papers]
        
        logger.info(f"筛选结果: {len(filtered_papers)}/{len(papers)} 篇论文")
        return filtered_papers
    
    def get_keyword_statistics(self, papers: List[Dict]) -> Dict:
        """
        获取关键词统计信息
        """
        if not papers:
            return {}
        
        keyword_counts = {}
        for paper in papers:
            if 'matched_keywords' in paper:
                for keyword in paper['matched_keywords']:
                    keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1
        
        # 按出现次数排序
        sorted_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
        
        return {
            'total_papers': len(papers),
            'keyword_frequency': dict(sorted_keywords),
            'avg_score': np.mean([p.get('match_score', 0) for p in papers])
        }


def test_paper_filter():
    """
    测试论文筛选功能
    """
    # 创建测试数据
    test_papers = [
        {
            'id': 'test1',
            'title': 'Deep Learning for Computer Vision',
            'abstract': 'This paper presents a novel deep learning approach for image recognition using convolutional neural networks.',
            'authors': ['Author 1'],
            'published': '2024-01-01',
            'categories': ['cs.CV']
        },
        {
            'id': 'test2',
            'title': 'Natural Language Processing with Transformers',
            'abstract': 'We propose a new transformer architecture for text generation and language understanding.',
            'authors': ['Author 2'],
            'published': '2024-01-01',
            'categories': ['cs.CL']
        },
        {
            'id': 'test3',
            'title': 'Quantum Computing Algorithms',
            'abstract': 'This paper discusses quantum algorithms for optimization problems.',
            'authors': ['Author 3'],
            'published': '2024-01-01',
            'categories': ['quant-ph']
        }
    ]
    
    filter_obj = PaperFilter()
    filtered_papers = filter_obj.filter_papers(test_papers)
    
    print(f"筛选结果: {len(filtered_papers)} 篇论文")
    for paper in filtered_papers:
        print(f"- {paper['title']}")
        print(f"  匹配分数: {paper.get('match_score', 0):.3f}")
        print(f"  匹配关键词: {paper.get('matched_keywords', [])}")
        print()


if __name__ == "__main__":
    test_paper_filter()
