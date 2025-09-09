"""
arXiv论文爬取模块
负责从arXiv获取最新的论文信息
"""

import arxiv
import feedparser
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import logging
import time
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ArxivCrawler:
    def __init__(self, config: Dict):
        self.config = config
        self.categories = config.get('categories', ['cs.AI', 'cs.LG'])
        self.batch_size = config.get('batch_size', 50)
        self.days_back = config.get('days_back', 1)
        self.max_total_papers = config.get('max_total_papers', 500)
        self.processed_papers = set()  # 用于去重
        
    def get_recent_papers_batch(self, start_index: int = 0) -> List[Dict]:
        """
        分批获取最近几天的论文
        """
        papers = []
        
        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.days_back)
        
        logger.info(f"获取第 {start_index//self.batch_size + 1} 批论文 ({start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')})")
        
        for category in self.categories:
            try:
                # 使用arxiv库搜索论文
                search = arxiv.Search(
                    query=f'cat:{category} AND submittedDate:[{start_date.strftime("%Y%m%d")} TO {end_date.strftime("%Y%m%d")}]',
                    max_results=self.batch_size,
                    sort_by=arxiv.SortCriterion.SubmittedDate,
                    sort_order=arxiv.SortOrder.Descending
                )
                
                # 跳过已处理的论文
                current_index = 0
                for paper in search.results():
                    if current_index < start_index:
                        current_index += 1
                        continue
                    if current_index >= start_index + self.batch_size:
                        break
                        
                    paper_info = {
                        'id': paper.entry_id.split('/')[-1],
                        'title': paper.title,
                        'abstract': paper.summary,
                        'authors': [author.name for author in paper.authors],
                        'published': paper.published,
                        'updated': paper.updated,
                        'categories': paper.categories,
                        'pdf_url': paper.pdf_url,
                        'primary_category': paper.primary_category,
                        'doi': paper.doi,
                        'journal_ref': paper.journal_ref
                    }
                    
                    # 去重检查
                    if paper_info['id'] not in self.processed_papers:
                        papers.append(paper_info)
                        self.processed_papers.add(paper_info['id'])
                    
                    current_index += 1
                    
                logger.info(f"从 {category} 获取到 {len([p for p in papers if category in p['categories']])} 篇新论文")
                time.sleep(1)  # 避免请求过于频繁
                
            except Exception as e:
                logger.error(f"获取 {category} 论文时出错: {e}")
                continue
                
        logger.info(f"本批获取到 {len(papers)} 篇唯一论文")
        return papers
    
    def get_all_recent_papers(self) -> List[Dict]:
        """
        获取所有最近的论文（分批处理）
        """
        all_papers = []
        start_index = 0
        
        while len(all_papers) < self.max_total_papers:
            batch_papers = self.get_recent_papers_batch(start_index)
            
            if not batch_papers:
                logger.info("没有更多论文可获取")
                break
                
            all_papers.extend(batch_papers)
            start_index += self.batch_size
            
            # 如果获取的论文数量少于批次大小，说明已经获取完毕
            if len(batch_papers) < self.batch_size:
                break
                
        logger.info(f"总共获取到 {len(all_papers)} 篇论文")
        return all_papers
    
    def get_paper_by_id(self, paper_id: str) -> Optional[Dict]:
        """
        根据论文ID获取特定论文信息
        """
        try:
            search = arxiv.Search(id_list=[paper_id])
            paper = next(search.results())
            
            return {
                'id': paper.entry_id.split('/')[-1],
                'title': paper.title,
                'abstract': paper.summary,
                'authors': [author.name for author in paper.authors],
                'published': paper.published,
                'updated': paper.updated,
                'categories': paper.categories,
                'pdf_url': paper.pdf_url,
                'primary_category': paper.primary_category,
                'doi': paper.doi,
                'journal_ref': paper.journal_ref
            }
        except Exception as e:
            logger.error(f"获取论文 {paper_id} 时出错: {e}")
            return None
    
    def download_pdf(self, paper: Dict, download_dir: str = "downloads", max_size_mb: int = 50) -> Optional[str]:
        """
        下载论文PDF
        """
        try:
            if not os.path.exists(download_dir):
                os.makedirs(download_dir)
                
            paper_id = paper['id']
            pdf_url = paper['pdf_url']
            
            # 构建文件名
            safe_title = "".join(c for c in paper['title'] if c.isalnum() or c in (' ', '-', '_')).rstrip()
            filename = f"{paper_id}_{safe_title[:50]}.pdf"
            filepath = os.path.join(download_dir, filename)
            
            # 如果文件已存在，直接返回路径
            if os.path.exists(filepath):
                logger.info(f"PDF已存在: {filepath}")
                return filepath
            
            # 下载PDF
            response = requests.get(pdf_url, stream=True)
            response.raise_for_status()
            
            # 检查文件大小
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > max_size_mb * 1024 * 1024:
                logger.warning(f"PDF文件过大 ({int(content_length)/1024/1024:.1f}MB > {max_size_mb}MB): {paper_id}")
                return None
            
            with open(filepath, 'wb') as f:
                downloaded_size = 0
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    
                    # 检查下载大小
                    if downloaded_size > max_size_mb * 1024 * 1024:
                        f.close()
                        os.remove(filepath)
                        logger.warning(f"PDF文件下载过程中超过大小限制: {paper_id}")
                        return None
                    
            logger.info(f"PDF下载成功: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"下载PDF失败 {paper['id']}: {e}")
            return None
    
    def cleanup_pdf(self, filepath: str) -> bool:
        """
        清理PDF文件
        """
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                logger.info(f"PDF文件已删除: {filepath}")
                return True
        except Exception as e:
            logger.error(f"删除PDF文件失败 {filepath}: {e}")
        return False


def test_arxiv_crawler():
    """
    测试arXiv爬取功能
    """
    config = {
        'categories': ['cs.AI', 'cs.LG'],
        'max_results': 5,
        'days_back': 1
    }
    
    crawler = ArxivCrawler(config)
    papers = crawler.get_recent_papers()
    
    print(f"获取到 {len(papers)} 篇论文:")
    for paper in papers[:3]:  # 只显示前3篇
        print(f"- {paper['title']}")
        print(f"  作者: {', '.join(paper['authors'][:3])}")
        print(f"  摘要: {paper['abstract'][:200]}...")
        print()


if __name__ == "__main__":
    test_arxiv_crawler()
