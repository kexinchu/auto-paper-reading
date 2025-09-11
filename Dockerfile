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

# 安装CUDA支持（如果需要GPU加速）
# 注意：这需要nvidia-docker运行时
# RUN apt-get update && apt-get install -y \
#     nvidia-cuda-toolkit \
#     && rm -rf /var/lib/apt/lists/*
# 通过pip安装CUDA支持，更轻量级
# RUN apt-get update && apt-get install -y \
#     && rm -rf /var/lib/apt/lists/*

# 复制requirements文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 安装SGLang
RUN pip install --no-cache-dir "sglang[all]"

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p downloads logs models

# 设置权限
RUN chmod +x *.sh

# 暴露端口（SGLang默认端口）
EXPOSE 30000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:30000/health || exit 1

# 启动命令 - 保持容器运行但不自动启动SGLang服务
CMD ["tail", "-f", "/dev/null"]
