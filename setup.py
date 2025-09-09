#!/usr/bin/env python3
"""
安装脚本
"""

import os
import sys
import subprocess

def install_requirements():
    """安装依赖包"""
    print("正在安装依赖包...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("依赖包安装成功")
        return True
    except subprocess.CalledProcessError as e:
        print(f"依赖包安装失败: {e}")
        return False

def create_directories():
    """创建必要的目录"""
    directories = ["downloads", "logs"]
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"创建目录: {directory}")

def check_config():
    """检查配置文件"""
    config_files = ["config.yaml", "keywords.yaml"]
    for config_file in config_files:
        if not os.path.exists(config_file):
            print(f"警告: 配置文件 {config_file} 不存在")
        else:
            print(f"配置文件 {config_file} 存在")

def main():
    print("自动论文阅读工具安装程序")
    print("=" * 40)
    
    # 检查Python版本
    if sys.version_info < (3, 8):
        print("错误: 需要Python 3.8或更高版本")
        sys.exit(1)
    
    print(f"Python版本: {sys.version}")
    
    # 安装依赖
    if not install_requirements():
        print("安装失败，请检查网络连接和Python环境")
        sys.exit(1)
    
    # 创建目录
    create_directories()
    
    # 检查配置
    check_config()
    
    print("\n安装完成！")
    print("\n下一步:")
    print("1. 编辑 config.yaml 配置邮件设置")
    print("2. 编辑 keywords.yaml 设置关键词")
    print("3. 运行 python run.py --test 测试组件")
    print("4. 运行 python run.py --run-now 立即执行一次")
    print("5. 运行 python run.py 启动定时任务")

if __name__ == "__main__":
    main()
