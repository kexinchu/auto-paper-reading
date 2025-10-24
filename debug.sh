#!/bin/bash

# 调试模式启动脚本
# 用于交互式调试和问题记录

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
    echo "🔧 调试模式启动脚本"
    echo "=================="
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --start           启动调试容器"
    echo "  --enter           进入调试容器"
    echo "  --stop            停止调试容器"
    echo "  --logs            查看调试日志"
    echo "  --status          查看容器状态"
    echo "  --clean           清理调试环境"
    echo "  --help            显示此帮助信息"
    echo ""
    echo "调试流程:"
    echo "  1. ./debug.sh --start    启动调试容器"
    echo "  2. ./debug.sh --enter    进入容器调试"
    echo "  3. 在容器内测试和安装依赖"
    echo "  4. 记录所有问题和解决方案"
    echo "  5. ./debug.sh --stop     停止调试"
    echo ""
}

# 启动调试容器
start_debug() {
    print_step "启动调试容器..."
    
    # 创建调试日志目录
    mkdir -p debug_logs
    
    # 启动调试容器
    docker-compose -f docker-compose.debug.yml up -d --build
    
    if [ $? -eq 0 ]; then
        print_message "调试容器启动成功"
        print_message "容器名称: paper-reader-debug"
        print_message "使用 './debug.sh --enter' 进入容器"
    else
        print_error "调试容器启动失败"
        exit 1
    fi
}

# 进入调试容器
enter_debug() {
    print_step "进入调试容器..."
    
    if ! docker ps | grep -q "paper-reader-debug"; then
        print_error "调试容器未运行，请先运行 './debug.sh --start'"
        exit 1
    fi
    
    print_message "进入调试容器..."
    print_message "提示："
    print_message "  - 使用 'exit' 退出容器"
    print_message "  - 记录所有安装的包和遇到的问题"
    print_message "  - 测试SGLang启动命令"
    print_message "  - 检查所有依赖是否完整"
    echo ""
    
    docker exec -it paper-reader-debug /bin/bash
}

# 停止调试容器
stop_debug() {
    print_step "停止调试容器..."
    docker-compose -f docker-compose.debug.yml down
    print_message "调试容器已停止"
}

# 查看调试日志
show_logs() {
    print_step "查看调试日志..."
    docker-compose -f docker-compose.debug.yml logs -f paper-reader-debug
}

# 查看容器状态
show_status() {
    print_step "查看容器状态..."
    docker-compose -f docker-compose.debug.yml ps
    echo ""
    print_message "容器详细信息:"
    docker ps | grep paper-reader-debug || echo "容器未运行"
}

# 清理调试环境
clean_debug() {
    print_step "清理调试环境..."
    docker-compose -f docker-compose.debug.yml down -v
    docker rmi auto-paper-reading_paper-reader-debug 2>/dev/null || true
    print_message "调试环境已清理"
}

# 主函数
main() {
    local action=${1:-"--help"}
    
    echo "🔧 调试模式启动脚本"
    echo "=================="
    
    case ${action} in
        "--start")
            start_debug
            ;;
        "--enter")
            enter_debug
            ;;
        "--stop")
            stop_debug
            ;;
        "--logs")
            show_logs
            ;;
        "--status")
            show_status
            ;;
        "--clean")
            clean_debug
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
