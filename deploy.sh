#!/bin/bash

# 自动论文阅读工具部署脚本
# 支持Docker部署

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印带颜色的消息
print_message() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# 检查Docker环境
check_docker() {
    print_step "检查Docker环境..."
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker未安装，请先安装Docker"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose未安装，请先安装Docker Compose"
        exit 1
    fi
    
    print_message "Docker环境检查通过"
}

# 检查模型路径
check_model_path() {
    print_step "检查模型路径..."
    
    MODEL_PATH="/home/kec23008/docker-sys/llm-security/Models"
    if [ ! -d "$MODEL_PATH" ]; then
        print_warning "模型路径不存在: $MODEL_PATH"
        print_message "请确保模型已下载到指定路径"
        read -p "是否继续部署？(y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        print_message "模型路径检查通过: $MODEL_PATH"
    fi
}

# 检查配置文件
check_config() {
    print_step "检查配置文件..."
    
    if [ ! -f "config.yaml" ]; then
        print_error "config.yaml文件不存在"
        exit 1
    fi
    
    if [ ! -f "topics.yaml" ]; then
        print_error "topics.yaml文件不存在"
        exit 1
    fi
    
    print_message "配置文件检查通过"
}

# 创建必要目录
create_directories() {
    print_step "创建必要目录..."
    mkdir -p downloads logs
    print_message "目录创建完成"
}

# 构建和启动服务
deploy_services() {
    print_step "构建和启动Docker服务..."
    
    # 构建镜像
    print_message "构建Docker镜像..."
    docker-compose build
    
    # 启动服务
    print_message "启动服务..."
    docker-compose up -d
    
    print_message "服务启动完成"
}

# 验证部署
verify_deployment() {
    print_step "验证部署..."
    
    # 等待服务启动
    print_message "等待服务启动..."
    sleep 30
    
    # 检查服务状态
    print_message "检查服务状态..."
    docker-compose ps
    
    # 检查SGLang服务器健康状态
    print_message "检查SGLang服务器健康状态..."
    if curl -s http://localhost:8089/health > /dev/null; then
        print_message "SGLang服务器运行正常"
    else
        print_warning "SGLang服务器可能未完全启动，请稍后检查"
    fi
    
    print_message "部署验证完成"
}

# 显示使用说明
show_usage() {
    print_message "部署完成！"
    echo ""
    echo "使用说明："
    echo "  查看日志: docker-compose logs -f"
    echo "  停止服务: docker-compose down"
    echo "  重启服务: docker-compose restart"
    echo "  测试组件: docker-compose exec paper-reader python main.py --test"
    echo "  立即执行: docker-compose exec paper-reader python main.py --run-now"
    echo ""
    echo "服务地址："
    echo "  SGLang API: http://localhost:8089"
    echo "  Redis: localhost:6379"
}

# 主函数
main() {
    echo "=========================================="
    echo "  自动论文阅读工具 - Docker部署脚本"
    echo "  SGLang + Qwen2.5-0.5B"
    echo "=========================================="
    echo
    
    check_docker
    check_model_path
    check_config
    create_directories
    deploy_services
    verify_deployment
    show_usage
}

# 错误处理
trap 'print_error "部署过程中发生错误"; exit 1' ERR

# 运行主函数
main "$@"