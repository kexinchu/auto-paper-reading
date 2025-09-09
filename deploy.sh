#!/bin/bash

# 自动论文阅读工具部署脚本
# 使用SGLang + Qwen2.5-0.5B模型

set -e

echo "🚀 开始部署自动论文阅读工具..."

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

# 检查Docker是否安装
check_docker() {
    print_step "检查Docker安装..."
    if ! command -v docker &> /dev/null; then
        print_error "Docker未安装，请先安装Docker"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose未安装，请先安装Docker Compose"
        exit 1
    fi
    
    print_message "Docker和Docker Compose已安装"
}

# 检查NVIDIA GPU支持
check_gpu() {
    print_step "检查GPU支持..."
    if command -v nvidia-smi &> /dev/null; then
        print_message "检测到NVIDIA GPU"
        nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits
    else
        print_warning "未检测到NVIDIA GPU，将使用CPU运行（性能较低）"
    fi
}

# 检查NVIDIA Container Toolkit
check_nvidia_docker() {
    print_step "检查NVIDIA Container Toolkit..."
    if docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi &> /dev/null; then
        print_message "NVIDIA Container Toolkit已正确安装"
    else
        print_warning "NVIDIA Container Toolkit未安装或配置不正确"
        print_warning "GPU加速可能不可用，但程序仍可运行"
    fi
}

# 创建必要的目录
create_directories() {
    print_step "创建必要的目录..."
    mkdir -p downloads logs models
    print_message "目录创建完成"
}

# 检查配置文件
check_config() {
    print_step "检查配置文件..."
    
    if [ ! -f "config.yaml" ]; then
        print_error "config.yaml文件不存在"
        exit 1
    fi
    
    if [ ! -f "keywords.yaml" ]; then
        print_error "keywords.yaml文件不存在"
        exit 1
    fi
    
    # 检查邮件配置
    if grep -q "your_email@gmail.com" config.yaml; then
        print_warning "请先配置config.yaml中的邮件设置"
        print_warning "编辑config.yaml文件，设置正确的邮件配置"
        read -p "是否继续部署？(y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    print_message "配置文件检查完成"
}

# 构建Docker镜像
build_images() {
    print_step "构建Docker镜像..."
    docker-compose build --no-cache
    print_message "Docker镜像构建完成"
}

# 启动服务
start_services() {
    print_step "启动服务..."
    docker-compose up -d
    print_message "服务启动完成"
}

# 等待服务就绪
wait_for_services() {
    print_step "等待服务就绪..."
    
    # 等待SGLang服务器启动
    print_message "等待SGLang服务器启动..."
    for i in {1..60}; do
        if curl -s http://localhost:30000/health &> /dev/null; then
            print_message "SGLang服务器已就绪"
            break
        fi
        if [ $i -eq 60 ]; then
            print_error "SGLang服务器启动超时"
            docker-compose logs sglang-server
            exit 1
        fi
        sleep 5
    done
    
    # 等待论文阅读应用启动
    print_message "等待论文阅读应用启动..."
    sleep 10
}

# 测试服务
test_services() {
    print_step "测试服务..."
    
    # 测试SGLang API
    print_message "测试SGLang API..."
    response=$(curl -s -X POST http://localhost:30000/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d '{
            "model": "default",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
            "max_tokens": 10
        }')
    
    if echo "$response" | grep -q "choices"; then
        print_message "SGLang API测试成功"
    else
        print_warning "SGLang API测试失败，但服务可能仍在启动中"
    fi
    
    # 测试论文阅读应用
    print_message "测试论文阅读应用..."
    docker-compose exec -T paper-reader python run.py --test
}

# 显示部署信息
show_deployment_info() {
    print_step "部署完成！"
    echo
    echo "📋 服务信息："
    echo "  - SGLang服务器: http://localhost:30000"
    echo "  - 健康检查: http://localhost:30000/health"
    echo "  - Redis缓存: localhost:6379"
    echo
    echo "📁 重要目录："
    echo "  - 配置文件: ./config.yaml"
    echo "  - 关键词配置: ./keywords.yaml"
    echo "  - 下载目录: ./downloads"
    echo "  - 日志目录: ./logs"
    echo
    echo "🔧 常用命令："
    echo "  - 查看日志: docker-compose logs -f"
    echo "  - 重启服务: docker-compose restart"
    echo "  - 停止服务: docker-compose down"
    echo "  - 测试组件: docker-compose exec paper-reader python run.py --test"
    echo "  - 立即执行: docker-compose exec paper-reader python run.py --run-now"
    echo
    echo "📖 更多信息请查看 DEPLOYMENT.md"
}

# 主函数
main() {
    echo "=========================================="
    echo "  自动论文阅读工具部署脚本"
    echo "  SGLang + Qwen2.5-0.5B"
    echo "=========================================="
    echo
    
    check_docker
    check_gpu
    check_nvidia_docker
    create_directories
    check_config
    build_images
    start_services
    wait_for_services
    test_services
    show_deployment_info
}

# 错误处理
trap 'print_error "部署过程中发生错误，请检查日志"; exit 1' ERR

# 运行主函数
main "$@"
