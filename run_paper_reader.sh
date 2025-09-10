#!/bin/bash

# 自动论文阅读工具一键运行脚本
# 支持本地运行和Docker部署

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

# 显示帮助信息
show_help() {
    echo "自动论文阅读工具 - 一键运行脚本"
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --local          本地运行模式"
    echo "  --docker         Docker运行模式"
    echo "  --test           测试模式（仅测试组件）"
    echo "  --run-now        立即执行一次任务"
    echo "  --setup          安装依赖"
    echo "  --help           显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 --local       本地运行"
    echo "  $0 --docker      使用Docker运行"
    echo "  $0 --test        测试所有组件"
    echo "  $0 --run-now     立即执行一次任务"
}

# 检查Python环境
check_python() {
    print_step "检查Python环境..."
    
    if ! command -v python3 &> /dev/null; then
        print_error "Python3未安装"
        exit 1
    fi
    
    python_version=$(python3 --version | cut -d' ' -f2)
    print_message "Python版本: $python_version"
    
    # 检查Python版本是否满足要求
    if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
        print_error "需要Python 3.8或更高版本"
        exit 1
    fi
}

# 检查配置文件
check_config() {
    print_step "检查配置文件..."
    
    if [ ! -f "config.yaml" ]; then
        print_error "config.yaml文件不存在"
        print_message "请复制config.yaml.example并配置"
        exit 1
    fi
    
    if [ ! -f "keywords.yaml" ]; then
        print_error "keywords.yaml文件不存在"
        print_message "请复制keywords.yaml.example并配置"
        exit 1
    fi
    
    # 检查邮件配置
    if grep -q "ckx.ict@gmail.com" config.yaml; then
        print_warning "请先配置config.yaml中的邮件设置"
        read -p "是否继续运行？(y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    print_message "配置文件检查完成"
}

# 安装依赖
install_dependencies() {
    print_step "安装Python依赖..."
    
    if [ -f "requirements.txt" ]; then
        pip3 install -r requirements.txt
        print_message "依赖安装完成"
    else
        print_error "requirements.txt文件不存在"
        exit 1
    fi
}

# 创建必要目录
create_directories() {
    print_step "创建必要目录..."
    mkdir -p downloads logs models
    print_message "目录创建完成"
}

# 本地运行模式
run_local() {
    print_step "启动本地运行模式..."
    
    # 检查是否需要启动SGLang服务器
    if ! curl -s http://localhost:30000/health &> /dev/null; then
        print_warning "SGLang服务器未运行，请先启动SGLang服务器"
        print_message "可以使用以下命令启动:"
        print_message "python sglang_server.py"
        read -p "是否继续运行（将使用摘要模式）？(y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
    
    # 启动主程序
    python3 main.py
}

# Docker运行模式
run_docker() {
    print_step "启动Docker运行模式..."
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker未安装"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose未安装"
        exit 1
    fi
    
    # 构建并启动服务
    docker-compose up -d
    
    print_message "Docker服务已启动"
    print_message "查看日志: docker-compose logs -f"
    print_message "停止服务: docker-compose down"
}

# 测试模式
run_test() {
    print_step "运行测试模式..."
    
    if [ -f "main.py" ]; then
        python3 main.py --test
    else
        print_error "main.py文件不存在"
        exit 1
    fi
}

# 立即执行模式
run_now() {
    print_step "立即执行一次任务..."
    
    if [ -f "main.py" ]; then
        python3 main.py --run-now
    else
        print_error "main.py文件不存在"
        exit 1
    fi
}

# 主函数
main() {
    echo "=========================================="
    echo "  自动论文阅读工具 - 一键运行脚本"
    echo "  SGLang + Qwen2.5-0.5B"
    echo "=========================================="
    echo
    
    # 解析命令行参数
    case "${1:-}" in
        --local)
            check_python
            check_config
            create_directories
            run_local
            ;;
        --docker)
            check_config
            run_docker
            ;;
        --test)
            check_python
            check_config
            create_directories
            run_test
            ;;
        --run-now)
            check_python
            check_config
            create_directories
            run_now
            ;;
        --setup)
            check_python
            install_dependencies
            create_directories
            print_message "安装完成！请配置config.yaml和keywords.yaml文件"
            ;;
        --help|-h)
            show_help
            ;;
        "")
            print_error "请指定运行模式"
            echo ""
            show_help
            exit 1
            ;;
        *)
            print_error "未知选项: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# 错误处理
trap 'print_error "脚本执行过程中发生错误"; exit 1' ERR

# 运行主函数
main "$@"
