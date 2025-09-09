# Docker部署指南

本指南将帮助你在服务器上使用Docker部署基于SGLang的论文阅读工具。

## 系统要求

### 硬件要求
- **GPU**: NVIDIA GPU (推荐RTX 3080或更高)
- **内存**: 至少16GB RAM
- **存储**: 至少50GB可用空间
- **CPU**: 4核心以上

### 软件要求
- Docker 20.10+
- Docker Compose 2.0+
- NVIDIA Container Toolkit (用于GPU支持)
- nvidia-docker2 (可选，推荐)

## 安装NVIDIA Container Toolkit

### Ubuntu/Debian
```bash
# 添加NVIDIA包仓库
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# 安装nvidia-docker2
sudo apt-get update && sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker
```

### CentOS/RHEL
```bash
# 添加NVIDIA包仓库
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.repo | sudo tee /etc/yum.repos.d/nvidia-docker.repo

# 安装nvidia-docker2
sudo yum install -y nvidia-docker2
sudo systemctl restart docker
```

## 部署步骤

### 1. 克隆项目
```bash
git clone <your-repo-url>
cd auto-paper-reading
```

### 2. 配置环境

#### 2.1 配置邮件设置
编辑 `config.yaml`:
```yaml
email:
  smtp_server: "smtp.gmail.com"
  smtp_port: 587
  sender_email: "your_email@gmail.com"
  sender_password: "your_app_password"
  recipient_email: "your_email@gmail.com"
```

#### 2.2 配置关键词
编辑 `keywords.yaml` 添加你感兴趣的关键词。

#### 2.3 配置模型参数
在 `config.yaml` 中调整模型配置:
```yaml
model:
  sglang_server_url: "http://sglang-server:30000"
  max_length: 2048
  temperature: 0.7
  max_retries: 3
  retry_delay: 1
```

### 3. 构建和启动服务

#### 3.1 使用Docker Compose (推荐)
```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

#### 3.2 单独启动SGLang服务器
```bash
# 启动SGLang服务器
docker run -d \
  --name qwen-sglang-server \
  --gpus all \
  -p 30000:30000 \
  -v $(pwd)/models:/app/models \
  auto-paper-reading \
  python sglang_server.py
```

### 4. 验证部署

#### 4.1 检查服务状态
```bash
# 检查容器状态
docker-compose ps

# 检查SGLang服务器健康状态
curl http://localhost:30000/health
```

#### 4.2 测试API
```bash
# 测试模型API
curl -X POST http://localhost:30000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "messages": [{"role": "user", "content": "Hello, how are you?"}],
    "temperature": 0.7,
    "max_tokens": 100
  }'
```

#### 4.3 测试完整流程
```bash
# 进入容器测试
docker-compose exec paper-reader python run.py --test
```

## 配置说明

### Docker Compose配置

#### 服务配置
- **sglang-server**: SGLang模型服务器
- **paper-reader**: 论文阅读应用
- **redis**: 缓存服务 (可选)

#### 端口映射
- `30000`: SGLang API服务端口
- `6379`: Redis服务端口

#### 卷挂载
- `./models:/app/models`: 模型文件存储
- `./config.yaml:/app/config.yaml`: 配置文件
- `./downloads:/app/downloads`: PDF下载目录
- `./logs:/app/logs`: 日志文件

### 环境变量

#### SGLang服务器
- `CUDA_VISIBLE_DEVICES`: 指定使用的GPU
- `MODEL_NAME`: 模型名称
- `HOST`: 服务器主机地址
- `PORT`: 服务器端口

#### 论文阅读应用
- `SGLANG_SERVER_URL`: SGLang服务器地址

## 监控和维护

### 1. 查看日志
```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f sglang-server
docker-compose logs -f paper-reader
```

### 2. 重启服务
```bash
# 重启所有服务
docker-compose restart

# 重启特定服务
docker-compose restart sglang-server
```

### 3. 更新服务
```bash
# 重新构建并启动
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### 4. 清理资源
```bash
# 停止并删除容器
docker-compose down

# 删除镜像
docker-compose down --rmi all

# 清理未使用的资源
docker system prune -a
```

## 性能优化

### 1. GPU优化
```yaml
# 在docker-compose.yml中调整GPU配置
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

### 2. 内存优化
```yaml
# 调整SGLang服务器内存使用
environment:
  - GPU_MEMORY_UTILIZATION=0.8
  - MAX_MODEL_LEN=4096
```

### 3. 并发优化
```yaml
# 在config.yaml中调整并发参数
model:
  max_retries: 3
  retry_delay: 1
```

## 故障排除

### 常见问题

#### 1. GPU不可用
```bash
# 检查NVIDIA驱动
nvidia-smi

# 检查Docker GPU支持
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi
```

#### 2. 模型下载失败
```bash
# 手动下载模型
docker-compose exec sglang-server python -c "
from transformers import AutoTokenizer, AutoModelForCausalLM
AutoTokenizer.from_pretrained('Qwen/Qwen2.5-0.5B-Instruct')
AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-0.5B-Instruct')
"
```

#### 3. 内存不足
```bash
# 检查内存使用
docker stats

# 调整模型参数
# 在sglang_server.py中减少max_model_len
```

#### 4. 网络连接问题
```bash
# 检查服务连通性
docker-compose exec paper-reader curl http://sglang-server:30000/health
```

### 日志分析

#### 查看错误日志
```bash
# 查看应用日志
tail -f logs/paper_reader.log

# 查看Docker日志
docker-compose logs --tail=100 paper-reader
```

## 安全考虑

### 1. 网络安全
- 使用防火墙限制端口访问
- 配置HTTPS (生产环境)
- 使用VPN或内网访问

### 2. 数据安全
- 定期备份配置文件
- 使用环境变量存储敏感信息
- 限制文件系统权限

### 3. 访问控制
- 配置邮件认证
- 使用强密码
- 定期更新依赖包

## 扩展功能

### 1. 负载均衡
```yaml
# 使用nginx进行负载均衡
nginx:
  image: nginx:alpine
  ports:
    - "80:80"
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf
```

### 2. 监控告警
```yaml
# 添加监控服务
prometheus:
  image: prom/prometheus
  ports:
    - "9090:9090"

grafana:
  image: grafana/grafana
  ports:
    - "3000:3000"
```

### 3. 自动备份
```bash
# 创建备份脚本
#!/bin/bash
docker-compose exec paper-reader tar -czf /app/backup-$(date +%Y%m%d).tar.gz /app/config.yaml /app/keywords.yaml
```

## 联系支持

如果遇到问题，请：
1. 查看日志文件
2. 检查系统资源
3. 验证配置文件
4. 提交Issue到项目仓库
