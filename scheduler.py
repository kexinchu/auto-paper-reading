"""
定时任务调度器
负责定时执行论文爬取、筛选、内容提取和邮件发送
"""

import time
import yaml
import logging
from datetime import datetime
import os
import sys
from typing import Dict
import pytz
import schedule

# 导入自定义模块
from arxiv_crawler import ArxivCrawler
from llm_paper_filter import LLMPaperFilter
from content_extractor import ContentExtractor
from email_sender import EmailSender

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('paper_reader.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class PaperReaderScheduler:
    def __init__(self, config_file: str = "config.yaml"):
        self.config_file = config_file
        self.config = self._load_config()
        self.crawler = None
        self.filter = None
        self.extractor = None
        self.email_sender = None
        
        self._initialize_components()
    
    def _load_config(self) -> Dict:
        """加载配置文件"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            raise
    
    def _initialize_components(self):
        """初始化各个组件"""
        try:
            # 初始化arXiv爬虫
            arxiv_config = self.config.get('arxiv', {})
            self.crawler = ArxivCrawler(arxiv_config)
            
            # 初始化LLM智能筛选器
            llm_config = self.config.get('llm', {})
            self.filter = LLMPaperFilter(llm_config)
            logger.info("使用LLM智能筛选器")
            
            # 初始化内容提取器
            llm_config = self.config.get('llm', {})
            self.extractor = ContentExtractor(llm_config)
            
            # 初始化邮件发送器
            email_config = self.config.get('email', {})
            self.email_sender = EmailSender(email_config)
            
            logger.info("所有组件初始化成功")
            
        except Exception as e:
            logger.error(f"组件初始化失败: {e}")
            raise
    
    def run_daily_task(self):
        """
        执行每日任务
        """
        logger.info("开始执行每日论文阅读任务")
        start_time = datetime.now()
        
        try:
            # 1. 分批爬取论文
            logger.info("步骤1: 分批爬取arXiv论文")
            all_papers = self.crawler.get_all_recent_papers()
            if not all_papers:
                logger.warning("没有获取到论文，任务结束")
                return
            
            logger.info(f"总共获取到 {len(all_papers)} 篇论文")
            
            # 2. 分批筛选论文
            logger.info("步骤2: 分批筛选相关论文")
            batch_size = self.config.get('filtering', {}).get('max_papers_per_batch', 10)
            all_filtered_papers = []
            
            for i in range(0, len(all_papers), batch_size):
                batch_papers = all_papers[i:i + batch_size]
                logger.info(f"处理第 {i//batch_size + 1} 批论文 ({len(batch_papers)} 篇)")
                
                filtered_batch = self.filter.filter_papers(batch_papers)
                all_filtered_papers.extend(filtered_batch)
                
                logger.info(f"本批筛选出 {len(filtered_batch)} 篇相关论文")
            
            if not all_filtered_papers:
                logger.warning("没有找到相关论文，发送空摘要邮件")
                self.email_sender.send_paper_summary([])
                return
            
            logger.info(f"总共筛选出 {len(all_filtered_papers)} 篇相关论文")
            
            # 3. 分批下载PDF和处理
            logger.info("步骤3: 根据需要下载PDF并提取内容")
            all_extracted_contents = []
            pdf_config = self.config.get('pdf', {})
            auto_delete = pdf_config.get('auto_delete', True)
            max_size_mb = pdf_config.get('max_pdf_size_mb', 50)
            extract_pages = pdf_config.get('extract_pages', 5)
            
            # 统计需要全文的论文数量
            fulltext_count = sum(1 for p in all_filtered_papers if p.get('need_fulltext', False))
            logger.info(f"共 {len(all_filtered_papers)} 篇论文，其中 {fulltext_count} 篇需要下载全文")
            
            for i, paper in enumerate(all_filtered_papers):
                need_fulltext = paper.get('need_fulltext', False)
                fulltext_mark = "📄" if need_fulltext else "📋"
                logger.info(f"{fulltext_mark} 处理第 {i+1}/{len(all_filtered_papers)} 篇论文: {paper.get('title', '')[:50]}...")
                
                # 只有标记为"需要全文"的论文才下载PDF
                if need_fulltext:
                    logger.info(f"  下载全文PDF...")
                    pdf_path = self.crawler.download_pdf(paper, max_size_mb=max_size_mb)
                    if pdf_path:
                        paper['pdf_path'] = pdf_path
                    
                    # 提取内容
                    if pdf_path and os.path.exists(pdf_path):
                        result = self.extractor.extract_from_pdf(pdf_path, paper, max_pages=extract_pages)
                        
                        # 自动删除PDF
                        if auto_delete:
                            self.crawler.cleanup_pdf(pdf_path)
                    else:
                        logger.warning("  PDF下载失败，使用摘要")
                        result = self.extractor.extract_from_abstract(paper)
                else:
                    # 只使用摘要
                    logger.info(f"  仅使用摘要（无需全文）")
                    result = self.extractor.extract_from_abstract(paper)
                
                all_extracted_contents.append(result)
            
            # 4. 发送邮件
            logger.info("步骤4: 发送邮件")
            success = self.email_sender.send_paper_summary(all_extracted_contents)
            
            if success:
                logger.info("每日任务执行成功")
            else:
                logger.error("邮件发送失败")
            
            # 记录执行时间
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.info(f"任务执行完成，耗时: {duration:.2f} 秒")
            
        except Exception as e:
            logger.error(f"每日任务执行失败: {e}")
            # 发送错误通知邮件
            try:
                error_content = [{
                    'title': '任务执行错误',
                    'authors': '系统',
                    'extracted_content': f'今日论文阅读任务执行失败: {str(e)}\n\n错误详情:\n{str(e)}\n\n请检查系统日志获取更多信息。',
                    'extraction_time': datetime.now().isoformat(),
                    'source': 'error'
                }]
                self.email_sender.send_paper_summary(error_content, "任务执行错误")
                logger.info("错误通知邮件已发送")
            except Exception as email_error:
                logger.error(f"发送错误通知邮件失败: {email_error}")
    
    def setup_schedule(self):
        """设置定时任务"""
        schedule_config = self.config.get('schedule', {})
        run_time = schedule_config.get('time', '22:30')
        timezone_str = schedule_config.get('timezone', 'America/New_York')
        enable_scheduler = schedule_config.get('enable_scheduler', True)
        
        if not enable_scheduler:
            logger.info("定时任务已禁用")
            return
        
        # 设置时区
        try:
            timezone = pytz.timezone(timezone_str)
            logger.info(f"使用时区: {timezone_str}")
        except Exception as e:
            logger.error(f"时区设置失败: {e}")
            timezone = pytz.timezone('America/New_York')
        
        # 设置每日任务
        schedule.every().day.at(run_time).do(self.run_daily_task)
        
        logger.info(f"定时任务已设置，每日 {run_time} ({timezone_str}) 执行")
    
    def run_scheduler(self):
        """运行调度器"""
        logger.info("启动论文阅读调度器")
        
        # 设置定时任务
        self.setup_schedule()
        
        # 可选：立即执行一次任务（用于测试）
        if len(sys.argv) > 1 and sys.argv[1] == '--run-now':
            logger.info("立即执行一次任务")
            self.run_daily_task()
        
        # 主循环
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # 每分钟检查一次
                
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在停止调度器...")
        except Exception as e:
            logger.error(f"调度器运行错误: {e}")
        finally:
            logger.info("调度器已停止")
    
    def test_components(self):
        """测试各个组件"""
        logger.info("开始测试各个组件")
        
        try:
            # 测试arXiv爬虫
            logger.info("测试arXiv爬虫...")
            papers = self.crawler.get_all_recent_papers()
            logger.info(f"arXiv爬虫测试成功，获取到 {len(papers)} 篇论文")
            
            # 测试论文筛选
            logger.info("测试论文筛选...")
            if papers:
                filtered_papers = self.filter.filter_papers(papers[:10])  # 只测试前10篇
                logger.info(f"论文筛选测试成功，筛选出 {len(filtered_papers)} 篇论文")
            else:
                logger.warning("没有论文可供筛选测试")
                filtered_papers = []
            
            # 测试内容提取
            if filtered_papers:
                logger.info("测试内容提取...")
                extracted_contents = self.extractor.batch_extract(filtered_papers[:2])  # 只测试前2篇
                logger.info(f"内容提取测试成功，提取了 {len(extracted_contents)} 篇论文内容")
            
            # 测试邮件发送
            logger.info("测试邮件发送...")
            if self.email_sender.test_connection():
                logger.info("邮件发送测试成功")
            else:
                logger.error("邮件发送测试失败")
            
            logger.info("所有组件测试完成")
            
        except Exception as e:
            logger.error(f"组件测试失败: {e}")


def main():
    """主函数"""
    try:
        scheduler = PaperReaderScheduler()
        
        # 检查命令行参数
        if len(sys.argv) > 1:
            if sys.argv[1] == '--test':
                scheduler.test_components()
            elif sys.argv[1] == '--run-now':
                scheduler.run_daily_task()
            else:
                print("用法: python scheduler.py [--test|--run-now]")
                print("  --test: 测试各个组件")
                print("  --run-now: 立即执行一次任务")
        else:
            # 正常运行调度器
            scheduler.run_scheduler()
            
    except Exception as e:
        logger.error(f"程序启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
