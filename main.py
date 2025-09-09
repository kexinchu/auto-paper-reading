#!/usr/bin/env python3
"""
自动论文阅读工具主程序
整合所有功能模块
"""

import sys
import os
import argparse
import logging
from datetime import datetime
import pytz

# 添加当前目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scheduler import PaperReaderScheduler

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('paper_reader.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='自动论文阅读工具')
    parser.add_argument('--config', default='config.yaml', help='配置文件路径')
    parser.add_argument('--test', action='store_true', help='测试所有组件')
    parser.add_argument('--run-now', action='store_true', help='立即执行一次任务')
    parser.add_argument('--daemon', action='store_true', help='后台运行模式')
    parser.add_argument('--timezone', help='指定时区（如：America/New_York）')
    
    args = parser.parse_args()
    
    try:
        # 创建调度器
        scheduler = PaperReaderScheduler(args.config)
        
        # 如果指定了时区，更新配置
        if args.timezone:
            scheduler.config['schedule']['timezone'] = args.timezone
            logger.info(f"使用时区: {args.timezone}")
        
        if args.test:
            logger.info("开始测试所有组件...")
            scheduler.test_components()
            logger.info("测试完成")
            
        elif args.run_now:
            logger.info("立即执行一次任务...")
            scheduler.run_daily_task()
            logger.info("任务执行完成")
            
        else:
            logger.info("启动定时任务调度器...")
            if args.daemon:
                logger.info("后台运行模式")
                # 这里可以添加后台运行的逻辑
            scheduler.run_scheduler()
            
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在退出...")
    except Exception as e:
        logger.error(f"程序运行错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
