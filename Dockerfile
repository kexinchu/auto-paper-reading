# 使用官方Python镜像作为基础镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制requirements文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p downloads logs

# 设置权限
RUN chmod +x *.sh || true

# 健康检查（检查应用是否运行）
HEALTHCHECK --interval=60s --timeout=10s --start-period=10s --retries=3 \
    CMD ps aux | grep -v grep | grep python || exit 1

# 运行应用
CMD ["python", "main.py"]
