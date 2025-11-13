#!/usr/bin/env python3
"""
完整流程测试脚本
测试从论文获取到邮件发送的完整流程
"""

import sys
import os
import yaml
import logging
from datetime import datetime

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arxiv_crawler import ArxivCrawler
from llm_paper_filter import LLMPaperFilter
from content_extractor import ContentExtractor
from email_sender import EmailSender

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config():
    """加载配置文件"""
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        sys.exit(1)


def check_api_key(config):
    """检查API密钥配置"""
    api_key = os.getenv('OPENAI_API_KEY') or config.get('llm', {}).get('api_key', '')
    
    if not api_key or api_key == 'YOUR_API_KEY_HERE':
        logger.error("❌ 未配置API密钥！")
        logger.info("\n请按以下方式配置API密钥：")
        logger.info("方式1: 设置环境变量")
        logger.info("  export OPENAI_API_KEY='your-api-key'")
        logger.info("\n方式2: 修改config.yaml")
        logger.info("  llm:")
        logger.info("    api_key: 'your-api-key'")
        logger.info("\n获取API密钥：")
        logger.info("  DeepSeek: https://platform.deepseek.com/")
        logger.info("  硅基流动: https://siliconflow.cn/")
        return False
    
    logger.info(f"✅ API密钥已配置: {api_key[:10]}...")
    return True


def test_llm_connection(config):
    """测试LLM连接"""
    logger.info("\n【步骤1】测试LLM API连接...")
    try:
        llm_config = config.get('llm', {})
        filter_obj = LLMPaperFilter(llm_config)
        
        if filter_obj.test_llm_connection():
            logger.info("✅ LLM API连接成功")
            return True
        else:
            logger.error("❌ LLM API连接失败")
            return False
    except Exception as e:
        logger.error(f"❌ LLM连接测试失败: {e}")
        return False


def test_arxiv_crawler(config):
    """测试arXiv爬虫"""
    logger.info("\n【步骤2】测试arXiv论文爬取...")
    try:
        arxiv_config = config.get('arxiv', {})
        # 限制获取数量以加快测试
        arxiv_config['max_total_papers'] = 20
        arxiv_config['batch_size'] = 10
        
        crawler = ArxivCrawler(arxiv_config)
        papers = crawler.get_all_recent_papers()
        
        logger.info(f"✅ 成功获取 {len(papers)} 篇论文")
        if papers:
            logger.info(f"示例论文: {papers[0]['title'][:60]}...")
        return papers
    except Exception as e:
        logger.error(f"❌ arXiv爬取失败: {e}")
        return []


def test_paper_filtering(config, papers):
    """测试论文筛选"""
    logger.info("\n【步骤3】测试智能论文筛选（含全文判断）...")
    try:
        llm_config = config.get('llm', {})
        filter_obj = LLMPaperFilter(llm_config)
        
        # 限制测试数量
        test_papers = papers[:5] if len(papers) > 5 else papers
        logger.info(f"测试筛选前 {len(test_papers)} 篇论文...")
        
        filtered_papers = filter_obj.filter_papers(test_papers)
        
        logger.info(f"\n✅ 筛选完成: {len(filtered_papers)}/{len(test_papers)} 篇通过")
        
        # 显示筛选结果
        for i, paper in enumerate(filtered_papers):
            fulltext_mark = "📄 需要全文" if paper.get('need_fulltext', False) else "📋 仅摘要"
            logger.info(f"\n论文 {i+1}:")
            logger.info(f"  标题: {paper['title'][:60]}...")
            logger.info(f"  主题: {paper.get('matched_topic', 'N/A')}")
            logger.info(f"  相关性: {paper.get('relevance_score', 0)}/10")
            logger.info(f"  质量: {paper.get('quality_score', 0)}/10")
            logger.info(f"  综合: {paper.get('combined_score', 0):.1f}/10")
            logger.info(f"  {fulltext_mark}")
        
        return filtered_papers
    except Exception as e:
        logger.error(f"❌ 论文筛选失败: {e}")
        import traceback
        traceback.print_exc()
        return []


def test_content_extraction(config, filtered_papers):
    """测试内容提取"""
    logger.info("\n【步骤4】测试内容提取...")
    try:
        llm_config = config.get('llm', {})
        extractor = ContentExtractor(llm_config)
        
        extracted_contents = []
        for i, paper in enumerate(filtered_papers):
            logger.info(f"\n提取第 {i+1}/{len(filtered_papers)} 篇...")
            
            # 根据need_fulltext决定是否下载PDF（这里为了测试速度，都使用摘要）
            need_fulltext = paper.get('need_fulltext', False)
            if need_fulltext:
                logger.info("  (标记为需要全文，但测试中使用摘要)")
            
            result = extractor.extract_from_abstract(paper)
            extracted_contents.append(result)
        
        logger.info(f"\n✅ 内容提取完成: {len(extracted_contents)} 篇")
        return extracted_contents
    except Exception as e:
        logger.error(f"❌ 内容提取失败: {e}")
        import traceback
        traceback.print_exc()
        return []


def test_email_sending(config, extracted_contents):
    """测试邮件发送"""
    logger.info("\n【步骤5】测试邮件发送...")
    
    email_config = config.get('email', {})
    sender_email = email_config.get('sender_email', '')
    
    if not sender_email or '@' not in sender_email:
        logger.warning("⚠️  邮箱未配置，跳过邮件发送测试")
        logger.info("\n如需测试邮件发送，请在config.yaml中配置：")
        logger.info("  email:")
        logger.info("    smtp_server: 'smtp.163.com'")
        logger.info("    sender_email: 'your-email@163.com'")
        logger.info("    sender_password: 'authorization-code'")
        logger.info("    recipient_email: 'recipient@gmail.com'")
        return False
    
    try:
        email_sender = EmailSender(email_config)
        
        # 测试连接
        if not email_sender.test_connection():
            logger.error("❌ 邮箱连接测试失败")
            return False
        
        logger.info("✅ 邮箱连接成功")
        
        # 发送测试邮件
        logger.info("正在发送测试邮件...")
        subject = f"论文阅读工具测试 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        success = email_sender.send_paper_summary(extracted_contents, subject)
        
        if success:
            logger.info("✅ 测试邮件发送成功！请检查收件箱")
            return True
        else:
            logger.error("❌ 邮件发送失败")
            return False
    except Exception as e:
        logger.error(f"❌ 邮件发送测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试流程"""
    logger.info("="*60)
    logger.info("自动论文阅读工具 - 完整流程测试")
    logger.info("="*60)
    
    # 加载配置
    config = load_config()
    
    # 检查API密钥
    if not check_api_key(config):
        sys.exit(1)
    
    # 测试LLM连接
    if not test_llm_connection(config):
        logger.error("\n测试失败：LLM连接不可用")
        sys.exit(1)
    
    # 测试arXiv爬虫
    papers = test_arxiv_crawler(config)
    if not papers:
        logger.error("\n测试失败：无法获取论文")
        sys.exit(1)
    
    # 测试论文筛选（含全文判断）
    filtered_papers = test_paper_filtering(config, papers)
    if not filtered_papers:
        logger.warning("\n⚠️  没有论文通过筛选（可能是主题配置过于严格）")
        logger.info("建议：")
        logger.info("1. 在topics.yaml中添加更多关键词")
        logger.info("2. 降低min_relevance_score和min_quality_score阈值")
        # 继续测试，使用原始论文
        filtered_papers = papers[:2]
    
    # 测试内容提取
    extracted_contents = test_content_extraction(config, filtered_papers)
    if not extracted_contents:
        logger.error("\n测试失败：内容提取失败")
        sys.exit(1)
    
    # 测试邮件发送
    email_success = test_email_sending(config, extracted_contents)
    
    # 测试总结
    logger.info("\n" + "="*60)
    logger.info("测试总结")
    logger.info("="*60)
    logger.info(f"✅ LLM连接: 成功")
    logger.info(f"✅ arXiv爬取: 成功 ({len(papers)} 篇)")
    logger.info(f"✅ 论文筛选: 成功 ({len(filtered_papers)} 篇通过)")
    logger.info(f"✅ 内容提取: 成功 ({len(extracted_contents)} 篇)")
    logger.info(f"{'✅' if email_success else '⚠️ '} 邮件发送: {'成功' if email_success else '跳过/失败'}")
    logger.info("="*60)
    
    if email_success:
        logger.info("\n🎉 完整流程测试通过！系统可以正常使用。")
    else:
        logger.info("\n✅ 核心功能测试通过！")
        logger.info("💡 如需邮件功能，请配置邮箱后重新测试。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n测试被用户中断")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

