#!/bin/bash

# 快速启动脚本
# 自动检测环境并选择最佳运行方式

set -e

echo "🚀 自动论文阅读工具 - 快速启动"
echo "=================================="

# 检查Docker是否可用
if command -v docker &> /dev/null && command -v docker-compose &> /dev/null; then
    echo "检测到Docker环境，使用Docker模式启动..."
    ./run_paper_reader.sh --docker
else
    echo "使用本地Python环境启动..."
    
    # 检查Python环境
    if ! command -v python3 &> /dev/null; then
        echo "❌ Python3未安装，请先安装Python 3.8+"
        exit 1
    fi
    
    # 检查虚拟环境
    if [ ! -d "venv" ]; then
        echo "📦 创建虚拟环境..."
        python3 -m venv venv
    fi
    
    # 激活虚拟环境
    echo "🔧 激活虚拟环境..."
    source venv/bin/activate
    
    # 安装依赖
    echo "📥 安装依赖..."
    pip install -r requirements.txt
    
    # 启动程序
    echo "▶️  启动程序..."
    ./run_paper_reader.sh --local
fi
