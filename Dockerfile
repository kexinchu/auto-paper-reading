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
    && rm -rf /var/lib/apt/lists/*

# 安装CUDA支持（如果需要GPU加速）
# 注意：这需要nvidia-docker运行时
RUN apt-get update && apt-get install -y \
    nvidia-cuda-toolkit \
    && rm -rf /var/lib/apt/lists/*

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
RUN chmod +x run.py setup.py

# 暴露端口（SGLang默认端口）
EXPOSE 30000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:30000/health || exit 1

# 启动命令
CMD ["python", "sglang_server.py"]
