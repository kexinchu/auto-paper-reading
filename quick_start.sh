#!/bin/bash

# 自动论文阅读工具 - 完整执行入口
# 支持测试和完整任务执行

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
    echo "🚀 自动论文阅读工具 - 完整执行入口"
    echo "=================================="
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --test           测试所有组件"
    echo "  --run            执行完整任务（包含启动Qwen模型）"
    echo "  --help           显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 --test        测试所有组件"
    echo "  $0 --run         执行完整任务"
    echo "  $0               默认执行完整任务"
    echo ""
}

# 检查Docker环境
check_docker() {
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

# 测试模式
run_test() {
    print_step "启动测试模式..."
    
    # 启动测试环境
    ./docker_manager.sh test
    
    if [ $? -eq 0 ]; then
        print_message "测试环境启动成功，开始测试..."
        
        # 在容器中运行测试
        docker exec -it paper-reader-app python main.py --test
        
        if [ $? -eq 0 ]; then
            print_message "所有测试通过"
        else
            print_error "测试失败"
            exit 1
        fi
    else
        print_error "测试环境启动失败"
        exit 1
    fi
}

# 完整任务执行
run_full_task() {
    print_step "启动完整任务执行..."
    
    # 启动所有服务
    ./docker_manager.sh start
    
    if [ $? -eq 0 ]; then
        print_message "所有服务启动成功，开始执行任务..."
        
        # 在容器中执行任务
        docker exec -it paper-reader-app python main.py --run-now
        
        if [ $? -eq 0 ]; then
            print_message "任务执行完成"
        else
            print_error "任务执行失败"
            exit 1
        fi
    else
        print_error "服务启动失败"
        exit 1
    fi
}

# 主函数
main() {
    local action=${1:-"--run"}
    
    echo "🚀 自动论文阅读工具 - 完整执行入口"
    echo "=================================="
    
    # 检查环境
    check_docker
    check_config
    
    case ${action} in
        "--test")
            run_test
            ;;
        "--run")
            run_full_task
            ;;
        "--help"|"-h")
            show_help
            ;;
        *)
            print_error "未知选项: ${action}"
            show_help
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"
