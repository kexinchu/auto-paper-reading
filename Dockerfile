# 使用官方Python镜像作为基础镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    libnuma1 \
    libnuma-dev \
    wget \
    gnupg2 \
    && rm -rf /var/lib/apt/lists/*

# GPU支持通过nvidia-docker运行时提供

# 复制requirements文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p downloads logs models

# 设置权限
RUN chmod +x *.sh

# 暴露端口（SGLang默认端口）
EXPOSE 8089

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8089/health || exit 1

# 使用bash作为主进程，确保可以通过exec进入
CMD ["/bin/bash", "-c", "python -m sglang.launch_server --model-path /app/models/Qwen3-0.6B --host 0.0.0.0 --port 8089 --trust-remote-code --attention-backend flashinfer --decode-attention-backend flashinfer --disable-cuda-graph --mem-fraction-static 0.8 --max-running-requests 32 --max-queued-requests 64 & wait"]
