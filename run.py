#!/usr/bin/env python3
"""
论文阅读工具启动脚本
提供简单的命令行接口
"""

import sys
import os
import argparse
from scheduler import PaperReaderScheduler

def main():
    parser = argparse.ArgumentParser(description='自动论文阅读工具')
    parser.add_argument('--test', action='store_true', help='测试各个组件')
    parser.add_argument('--run-now', action='store_true', help='立即执行一次任务')
    parser.add_argument('--config', default='config.yaml', help='配置文件路径')
    parser.add_argument('--daemon', action='store_true', help='后台运行')
    
    args = parser.parse_args()
    
    try:
        scheduler = PaperReaderScheduler(args.config)
        
        if args.test:
            print("开始测试各个组件...")
            scheduler.test_components()
        elif args.run_now:
            print("立即执行一次任务...")
            scheduler.run_daily_task()
        else:
            print("启动定时任务调度器...")
            if args.daemon:
                print("后台运行模式")
                # 这里可以添加后台运行的逻辑
            scheduler.run_scheduler()
            
    except KeyboardInterrupt:
        print("\n收到中断信号，正在退出...")
    except Exception as e:
        print(f"程序运行错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
