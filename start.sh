#!/bin/bash

# 单容器论文阅读工具启动脚本
# 基于SGLang 0.4.7部署LLM并处理论文阅读

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
    echo "🚀 单容器论文阅读工具"
    echo "====================="
    echo ""
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --test           测试所有组件"
    echo "  --run            执行完整任务"
    echo "  --stop           停止服务"
    echo "  --restart        重启服务"
    echo "  --logs           查看日志"
    echo "  --status         查看状态"
    echo "  --debug          进入容器进行调试"
    echo "  --shell          进入容器shell"
    echo "  --help           显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0 --test        测试所有组件"
    echo "  $0 --run         执行完整任务"
    echo "  $0 --stop        停止服务"
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

# 检查容器状态
check_container_status() {
    if docker-compose ps | grep -q "paper-reader-app.*Up"; then
        return 0
    else
        return 1
    fi
}

# 检查镜像是否存在
check_image_exists() {
    local image_name="auto-paper-reading_paper-reader"
    if docker images | grep -q "${image_name}"; then
        return 0
    else
        return 1
    fi
}

# 检查容器是否存在（无论是否运行）
check_container_exists() {
    if docker ps -a | grep -q "paper-reader-app"; then
        return 0
    else
        return 1
    fi
}

# 智能启动服务
smart_start_service() {
    print_step "智能启动服务..."
    
    # 1. 检查容器是否正在运行
    if check_container_status; then
        print_message "容器已在运行，直接使用现有容器"
        return 0
    fi
    
    # 2. 检查容器是否存在但未运行
    if check_container_exists; then
        print_message "发现现有容器，启动现有容器..."
        docker-compose start
        if [ $? -eq 0 ]; then
            print_message "现有容器启动成功"
            return 0
        else
            print_warning "现有容器启动失败，将重新创建"
        fi
    fi
    
    # 3. 检查镜像是否存在
    if check_image_exists; then
        print_message "发现现有镜像，使用现有镜像创建容器..."
        docker-compose up -d --no-build
        if [ $? -eq 0 ]; then
            print_message "使用现有镜像创建容器成功"
            return 0
        else
            print_warning "使用现有镜像创建容器失败，将重新构建"
        fi
    fi
    
    # 4. 没有现有资源，需要构建新镜像
    print_message "未发现现有资源，构建新镜像..."
    docker-compose up -d --build
    
    if [ $? -eq 0 ]; then
        print_message "新镜像构建并启动成功"
        return 0
    else
        print_error "镜像构建失败"
        return 1
    fi
}

# 启动服务
start_service() {
    # 使用智能启动服务
    smart_start_service
    
    if [ $? -eq 0 ]; then
        print_message "服务启动成功"
        
        # 等待SGLang服务就绪
        print_message "等待SGLang服务启动..."
        local max_wait=120
        local wait_count=0
        
        while [ $wait_count -lt $max_wait ]; do
            if docker-compose exec -T paper-reader curl -f http://localhost:8089/health 2>/dev/null; then
                print_message "SGLang服务已就绪"
                return 0
            fi
            print_message "等待SGLang服务启动... ($((wait_count + 1))/$max_wait)"
            sleep 2
            wait_count=$((wait_count + 1))
        done
        
        print_warning "SGLang服务启动超时，但容器已启动"
        return 1
    else
        print_error "服务启动失败"
        return 1
    fi
}

# 测试模式
run_test() {
    print_step "启动测试模式..."
    
    if ! check_container_status; then
        print_message "容器未运行，正在启动..."
        start_service
    fi
    
    if [ $? -eq 0 ]; then
        print_message "开始测试..."
        
        # 在容器中运行测试
        docker-compose exec -T paper-reader python main.py --test
        
        if [ $? -eq 0 ]; then
            print_message "所有测试通过"
        else
            print_error "测试失败"
            exit 1
        fi
    else
        print_error "服务启动失败"
        exit 1
    fi
}

# 完整任务执行
run_full_task() {
    print_step "启动完整任务执行..."
    
    if ! check_container_status; then
        print_message "容器未运行，正在启动..."
        start_service
    fi
    
    if [ $? -eq 0 ]; then
        print_message "开始执行任务..."
        
        # 在容器中执行任务
        docker-compose exec -T paper-reader python main.py --run-now
        
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

# 停止服务
stop_service() {
    print_step "停止服务..."
    docker-compose down
    print_message "服务已停止"
}

# 重启服务
restart_service() {
    print_step "重启服务..."
    stop_service
    start_service
}

# 查看日志
show_logs() {
    print_step "查看服务日志..."
    docker-compose logs -f paper-reader
}

# 查看状态
show_status() {
    print_step "查看服务状态..."
    docker-compose ps
    echo ""
    print_message "SGLang服务状态:"
    if docker-compose exec -T paper-reader curl -f http://localhost:8089/health 2>/dev/null; then
        print_message "✅ SGLang服务运行正常"
    else
        print_warning "❌ SGLang服务未响应"
    fi
}

# 进入容器进行调试
enter_debug() {
    print_step "进入容器调试模式..."
    
    if ! check_container_status; then
        print_message "容器未运行，正在启动..."
        smart_start_service
    fi
    
    if [ $? -eq 0 ]; then
        print_message "进入容器调试模式..."
        print_message "提示：使用 'exit' 退出容器"
        docker-compose exec paper-reader bash
    else
        print_error "容器启动失败，无法进入调试模式"
        exit 1
    fi
}

# 进入容器shell
enter_shell() {
    print_step "进入容器shell..."
    
    if ! check_container_status; then
        print_message "容器未运行，正在启动..."
        smart_start_service
    fi
    
    if [ $? -eq 0 ]; then
        print_message "进入容器shell..."
        print_message "提示：使用 'exit' 退出容器"
        docker-compose exec paper-reader /bin/bash
    else
        print_error "容器启动失败，无法进入shell"
        exit 1
    fi
}

# 主函数
main() {
    local action=${1:-"--run"}
    
    echo "🚀 单容器论文阅读工具"
    echo "====================="
    
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
        "--stop")
            stop_service
            ;;
        "--restart")
            restart_service
            ;;
        "--logs")
            show_logs
            ;;
        "--status")
            show_status
            ;;
        "--debug")
            enter_debug
            ;;
        "--shell")
            enter_shell
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
