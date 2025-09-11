#!/bin/bash

# Docker容器和镜像管理脚本
# 智能检查并启动Docker服务

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

# 检查Docker是否可用
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

# 检查容器是否存在且运行
check_container_status() {
    local container_name=$1
    
    if docker ps -a --format "table {{.Names}}" | grep -q "^${container_name}$"; then
        if docker ps --format "table {{.Names}}" | grep -q "^${container_name}$"; then
            print_message "容器 ${container_name} 正在运行"
            return 0  # 容器存在且运行
        else
            print_warning "容器 ${container_name} 存在但未运行"
            return 1  # 容器存在但未运行
        fi
    else
        print_message "容器 ${container_name} 不存在"
        return 2  # 容器不存在
    fi
}

# 检查镜像是否存在
check_image_exists() {
    local image_name=$1
    
    # 如果镜像名称不包含标签，添加:latest
    if [[ ! "$image_name" == *":"* ]]; then
        image_name="${image_name}:latest"
    fi
    
    if docker images --format "table {{.Repository}}:{{.Tag}}" | grep -q "^${image_name}$"; then
        print_message "镜像 ${image_name} 存在"
        return 0
    else
        print_message "镜像 ${image_name} 不存在"
        return 1
    fi
}

# 启动容器
start_container() {
    local container_name=$1
    local image_name=$2
    
    print_step "启动容器 ${container_name}..."
    
    if docker start ${container_name} > /dev/null 2>&1; then
        print_message "容器 ${container_name} 启动成功"
        return 0
    else
        print_error "容器 ${container_name} 启动失败"
        return 1
    fi
}

# 创建并启动容器
create_and_start_container() {
    local container_name=$1
    local image_name=$2
    
    print_step "使用镜像 ${image_name} 创建容器 ${container_name}..."
    
    # 根据容器名称决定启动命令
    case ${container_name} in
        "qwen-sglang-server")
            docker run -d \
                --name ${container_name} \
                --gpus all \
                -p 30000:30000 \
                -v /home/kec23008/docker-sys/llm-security/Models:/app/models \
                -v $(pwd)/config.yaml:/app/config.yaml \
                -v $(pwd)/topics.yaml:/app/topics.yaml \
                -v $(pwd)/downloads:/app/downloads \
                -v $(pwd)/logs:/app/logs \
                -e CUDA_VISIBLE_DEVICES=0 \
                -e MODEL_NAME=/app/models/Qwen3-0.6B \
                -e HOST=0.0.0.0 \
                -e PORT=30000 \
                --restart unless-stopped \
                ${image_name} \
                python -m sglang.launch_server \
                --model-path /app/models/Qwen3-0.6B \
                --host 0.0.0.0 \
                --port 30000 \
                --trust-remote-code
            ;;
        "paper-reader-app")
            docker run -d \
                --name ${container_name} \
                -v $(pwd)/config.yaml:/app/config.yaml \
                -v $(pwd)/topics.yaml:/app/topics.yaml \
                -v $(pwd)/downloads:/app/downloads \
                -v $(pwd)/logs:/app/logs \
                -e SGLANG_SERVER_URL=http://qwen-sglang-server:30000 \
                --restart unless-stopped \
                ${image_name} \
                python main.py
            ;;
        *)
            print_error "未知的容器名称: ${container_name}"
            return 1
            ;;
    esac
    
    if [ $? -eq 0 ]; then
        print_message "容器 ${container_name} 创建并启动成功"
        return 0
    else
        print_error "容器 ${container_name} 创建失败"
        return 1
    fi
}

# 构建镜像
build_image() {
    local image_name=$1
    
    print_step "构建镜像 ${image_name}..."
    
    if docker build -t ${image_name} . > /dev/null 2>&1; then
        print_message "镜像 ${image_name} 构建成功"
        return 0
    else
        print_error "镜像 ${image_name} 构建失败"
        return 1
    fi
}

# 智能启动服务
smart_start_service() {
    local service_name=$1
    local image_name="paper-reader-${service_name}"
    local container_name=""
    
    case ${service_name} in
        "sglang-server")
            container_name="qwen-sglang-server"
            ;;
        "paper-reader")
            container_name="paper-reader-app"
            ;;
        *)
            print_error "未知的服务名称: ${service_name}"
            return 1
            ;;
    esac
    
    print_step "智能启动服务: ${service_name}"
    
    # 检查容器状态
    check_container_status ${container_name}
    local container_status=$?
    
    case ${container_status} in
        0)
            print_message "容器 ${container_name} 已在运行"
            # 对于sglang-server，需要确保容器内服务也在运行
            if [ "${service_name}" = "sglang-server" ]; then
                if ! check_container_service ${container_name} ${service_name}; then
                    print_message "容器内SGLang服务未运行，正在启动..."
                    start_container_service ${container_name} ${service_name}
                    return $?
                fi
            fi
            return 0
            ;;
        1)
            print_message "容器存在但未运行，启动容器..."
            start_container ${container_name} ${image_name}
            if [ $? -eq 0 ] && [ "${service_name}" = "sglang-server" ]; then
                # 容器启动后，确保SGLang服务也在运行
                sleep 3  # 等待容器完全启动
                if ! check_container_service ${container_name} ${service_name}; then
                    print_message "容器内SGLang服务未运行，正在启动..."
                    start_container_service ${container_name} ${service_name}
                    return $?
                fi
            fi
            return $?
            ;;
        2)
            # 容器不存在，检查镜像
            check_image_exists ${image_name}
            local image_exists=$?
            
            if [ ${image_exists} -eq 0 ]; then
                print_message "镜像存在，创建并启动容器..."
                create_and_start_container ${container_name} ${image_name}
                if [ $? -eq 0 ] && [ "${service_name}" = "sglang-server" ]; then
                    # 容器创建后，确保SGLang服务也在运行
                    sleep 3  # 等待容器完全启动
                    if ! check_container_service ${container_name} ${service_name}; then
                        print_message "容器内SGLang服务未运行，正在启动..."
                        start_container_service ${container_name} ${service_name}
                        return $?
                    fi
                fi
                return $?
            else
                print_message "镜像不存在，构建镜像并创建容器..."
                if build_image ${image_name}; then
                    create_and_start_container ${container_name} ${image_name}
                    if [ $? -eq 0 ] && [ "${service_name}" = "sglang-server" ]; then
                        # 容器创建后，确保SGLang服务也在运行
                        sleep 3  # 等待容器完全启动
                        if ! check_container_service ${container_name} ${service_name}; then
                            print_message "容器内SGLang服务未运行，正在启动..."
                            start_container_service ${container_name} ${service_name}
                            return $?
                        fi
                    fi
                    return $?
                else
                    return 1
                fi
            fi
            ;;
    esac
}

# 检查容器内服务状态
check_container_service() {
    local container_name=$1
    local service_name=$2
    
    case ${service_name} in
        "sglang-server")
            # 检查SGLang服务是否在运行 - 使用多种方法验证
            local check_result=$(docker exec ${container_name} bash -c "
                # 检查进程
                if pgrep -f 'sglang.launch_server' > /dev/null 2>&1; then
                    echo 'process_found'
                    exit 0
                fi
                
                # 检查端口
                if netstat -tlnp 2>/dev/null | grep -q ':30000.*LISTEN'; then
                    echo 'port_open'
                    exit 0
                fi
                
                # 检查HTTP健康检查
                if curl -s http://localhost:30000/health > /dev/null 2>&1; then
                    echo 'http_ok'
                    exit 0
                fi
                
                echo 'not_running'
                exit 1
            " 2>/dev/null)
            
            if [[ "$check_result" == "process_found" || "$check_result" == "port_open" || "$check_result" == "http_ok" ]]; then
                print_message "SGLang服务正在运行 (${check_result})"
                return 0
            else
                print_warning "SGLang服务未运行"
                return 1
            fi
            ;;
        *)
            print_message "服务 ${service_name} 检查完成"
            return 0
            ;;
    esac
}

# 启动容器内服务
start_container_service() {
    local container_name=$1
    local service_name=$2
    
    case ${service_name} in
        "sglang-server")
            print_step "启动容器内的SGLang服务..."
            
            # 检查服务是否已经在运行
            if check_container_service ${container_name} ${service_name}; then
                print_message "SGLang服务已在运行"
                return 0
            fi
            
            # 启动SGLang服务 - 使用nohup确保后台运行
            print_message "在容器内启动SGLang服务..."
            docker exec ${container_name} bash -c "
                nohup python -m sglang.launch_server \
                    --model-path /app/models/Qwen3-0.6B \
                    --host 0.0.0.0 \
                    --port 30000 \
                    --trust-remote-code \
                    > /tmp/sglang.log 2>&1 &
                echo \$! > /tmp/sglang.pid
            "
            
            if [ $? -eq 0 ]; then
                print_message "SGLang服务启动命令已发送"
                # 等待几秒让服务启动
                sleep 5
                
                # 验证服务是否真的启动了
                if check_container_service ${container_name} ${service_name}; then
                    print_message "SGLang服务启动成功"
                    return 0
                else
                    print_warning "SGLang服务启动后验证失败，检查日志..."
                    docker exec ${container_name} tail -20 /tmp/sglang.log 2>/dev/null || echo "无法读取日志"
                    return 1
                fi
            else
                print_error "SGLang服务启动失败"
                return 1
            fi
            ;;
        *)
            print_message "服务 ${service_name} 启动完成"
            return 0
            ;;
    esac
}

# 等待服务健康检查
wait_for_health() {
    local service_name=$1
    local max_attempts=60  # 增加等待时间
    local attempt=1
    
    print_step "等待服务 ${service_name} 健康检查..."
    
    case ${service_name} in
        "sglang-server")
            while [ ${attempt} -le ${max_attempts} ]; do
                # 检查容器内服务进程
                if check_container_service "qwen-sglang-server" ${service_name}; then
                    # 检查HTTP健康检查端点
                    if curl -s http://localhost:30000/health > /dev/null 2>&1; then
                        print_message "SGLang服务器健康检查通过"
                        return 0
                    fi
                fi
                
                print_message "等待SGLang服务器启动... (${attempt}/${max_attempts})"
                sleep 10
                attempt=$((attempt + 1))
            done
            print_error "SGLang服务器健康检查超时"
            return 1
            ;;
        *)
            print_message "服务 ${service_name} 启动完成"
            return 0
            ;;
    esac
}

# 主函数
main() {
    local action=${1:-"start"}
    
    check_docker
    
    case ${action} in
        "start")
            print_step "启动所有服务..."
            
            # 启动SGLang服务器容器
            if smart_start_service "sglang-server"; then
                # 确保容器内SGLang服务启动
                if start_container_service "qwen-sglang-server" "sglang-server"; then
                    wait_for_health "sglang-server"
                    
                    # 启动论文阅读应用
                    smart_start_service "paper-reader"
                else
                    print_error "容器内SGLang服务启动失败"
                    exit 1
                fi
            else
                print_error "SGLang服务器容器启动失败"
                exit 1
            fi
            ;;
        "test")
            print_step "启动测试环境..."
            
            # 启动SGLang服务器容器
            if smart_start_service "sglang-server"; then
                # 确保容器内SGLang服务启动
                if start_container_service "qwen-sglang-server" "sglang-server"; then
                    wait_for_health "sglang-server"
                    print_message "测试环境准备完成"
                else
                    print_error "容器内SGLang服务启动失败"
                    exit 1
                fi
            else
                print_error "SGLang服务器容器启动失败"
                exit 1
            fi
            ;;
        "stop")
            print_step "停止所有服务..."
            docker stop qwen-sglang-server paper-reader-app 2>/dev/null || true
            print_message "所有服务已停止"
            ;;
        "clean")
            print_step "清理所有容器和镜像..."
            docker stop qwen-sglang-server paper-reader-app 2>/dev/null || true
            docker rm qwen-sglang-server paper-reader-app 2>/dev/null || true
            docker rmi paper-reader-sglang-server paper-reader-paper-reader 2>/dev/null || true
            print_message "清理完成"
            ;;
        *)
            echo "用法: $0 [start|test|stop|clean]"
            echo "  start: 启动所有服务"
            echo "  test:  启动测试环境"
            echo "  stop:  停止所有服务"
            echo "  clean: 清理所有容器和镜像"
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"
