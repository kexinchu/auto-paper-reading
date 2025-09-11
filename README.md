# 自动论文阅读工具

一个基于Docker的智能论文阅读工具，能够自动从arXiv获取最新论文，使用Qwen模型进行智能筛选和内容提取，并通过邮件定时发送摘要。

## 🚀 功能特性

- 🔍 **自动爬取**: 从arXiv获取最新的学术论文
- 🎯 **智能筛选**: 基于LLM的智能论文筛选
- 🤖 **AI提取**: 使用SGLang + Qwen3-0.6B模型提取论文核心内容
- 📧 **邮件推送**: 定时发送格式化的论文摘要邮件
- ⏰ **定时任务**: 支持自定义时间自动执行
- 🐳 **Docker部署**: 智能容器管理，支持镜像和容器自动检查
- 🚀 **高性能**: 基于SGLang框架，支持GPU加速和并发处理
- 📊 **错误通知**: 任务失败时自动发送邮件通知

## 📋 系统要求

### 硬件要求
- **GPU**: NVIDIA GPU (推荐RTX 3080或更高)
- **内存**: 至少16GB RAM
- **存储**: 至少50GB可用空间
- **CPU**: 4核心以上

### 软件要求
- Docker 20.10+
- Docker Compose 2.0+
- NVIDIA Container Toolkit (用于GPU支持)

## 🛠️ 安装部署

### 1. 安装NVIDIA Container Toolkit

#### Ubuntu/Debian
```bash
# 添加NVIDIA包仓库
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# 安装nvidia-docker2
sudo apt-get update && sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker
```

#### CentOS/RHEL
```bash
# 添加NVIDIA包仓库
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.repo | sudo tee /etc/yum.repos.d/nvidia-docker.repo

# 安装nvidia-docker2
sudo yum install -y nvidia-docker2
sudo systemctl restart docker
```

### 2. 快速部署
```bash
# 克隆项目
git clone <your-repo-url>
cd auto-paper-reading

# 运行部署脚本
chmod +x deploy.sh
./deploy.sh
```

## ⚙️ 配置设置

### 邮件配置

编辑 `config.yaml` 文件中的邮件配置：

```yaml
email:
  smtp_server: "smtp.163.com"  # 163邮箱SMTP服务器
  smtp_port: 465
  sender_email: "chu1649158185@163.com"  # 发送邮箱
  sender_password: "your_163_password"  # 163邮箱授权码
  recipient_email: "ckx.ict@gmail.com"  # 接收邮箱
  use_tls: true
```

**重要**: 对于163邮箱，需要：
1. 开启SMTP服务
2. 获取客户端授权码
3. 使用授权码作为密码

### 主题配置

编辑 `topics.yaml` 文件，使用自然语言描述你感兴趣的研究主题：

```yaml
topics:
  - name: "Machine Learning & LLM"
    description: "Machine learning and large language model research, including transformer architectures, attention mechanisms, mixture of experts (MoE), diffusion models, foundation models, model pruning, quantization techniques, and KV cache optimization for efficient inference."
  
  - name: "Computer Systems"
    description: "Computer systems research focusing on memory technologies, including CXL (Compute Express Link) memory interconnects, RDMA (Remote Direct Memory Access) for high-performance computing, and advanced memory management techniques."
  
  - name: "Multimodal & Agents"
    description: "Multimodal learning and multi-agent systems research, including multi-modality approaches, multi-task learning, multi-agent coordination, security in AI systems, approximate nearest neighbor search (ANNS)."
```

### arXiv分类配置

在 `config.yaml` 中配置关注的学科分类：

```yaml
arxiv:
  categories: [
    "cs.AI",   # 人工智能
    "cs.LG",   # 机器学习
    "cs.CV",   # 计算机视觉与模式识别
    "cs.CL",   # 计算与语言
    "cs.NE",   # 神经与进化计算
    "cs.RO",   # 机器人学
    "cs.DC",   # 分布式、并行与集群计算
    "cs.SE",   # 软件工程
    "cs.DB",   # 数据库
    "cs.CR",   # 密码学与安全
    "cs.HC",   # 人机交互
    "cs.IR",   # 信息检索
    "cs.IT",   # 信息理论
    "cs.MM",   # 多媒体
    "cs.NI",   # 网络与互联网架构
    "cs.OS",   # 操作系统
    "cs.PL",   # 编程语言
    "cs.SI",   # 社会和信息网络
    "cs.SY"    # 系统与控制
  ]
```

## 🚀 使用方法

### 快速开始

```bash
# 测试所有组件
./quick_start.sh --test

# 执行完整任务（包含启动Qwen模型）
./quick_start.sh --run

# 查看帮助
./quick_start.sh --help
```

### Docker管理

```bash
# 启动所有服务
./docker_manager.sh start

# 启动测试环境
./docker_manager.sh test

# 停止所有服务
./docker_manager.sh stop

# 清理所有容器和镜像
./docker_manager.sh clean
```

### 智能容器管理

系统会自动检查并管理Docker容器和镜像：

- **容器存在且运行** → 直接使用
- **容器存在但未运行** → 启动容器
- **容器不存在但镜像存在** → 创建并启动容器
- **两者都不存在** → 构建镜像并创建容器

## 📧 邮件通知

### 正常邮件
- 每日论文摘要发送到配置的接收邮箱
- 包含论文标题、作者、核心内容摘要

### 错误通知
- 任务失败时自动发送错误邮件到 `ckx.ict@gmail.com`
- 包含详细错误信息和系统日志提示

## 🧪 测试验证

### 基础功能测试
```bash
# 测试arXiv爬虫和邮件发送
python3 -c "
from arxiv_crawler import ArxivCrawler
from email_sender import EmailSender
import yaml

# 测试爬虫
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

crawler = ArxivCrawler(config['arxiv'])
papers = crawler.get_all_recent_papers()
print(f'获取到 {len(papers)} 篇论文')

# 测试邮件
sender = EmailSender(config['email'])
if sender.test_connection():
    print('邮件连接测试成功')
"
```

## 📁 项目结构

```
auto-paper-reading/
├── quick_start.sh          # 完整执行入口
├── docker_manager.sh       # Docker智能管理脚本
├── run_paper_reader.sh     # 传统运行脚本
├── deploy.sh              # 部署脚本
├── config.yaml            # 主配置文件
├── topics.yaml            # 主题配置文件
├── requirements.txt       # Python依赖
├── Dockerfile            # Docker镜像构建文件
├── docker-compose.yml    # Docker Compose配置
├── arxiv_crawler.py      # arXiv爬虫模块
├── llm_paper_filter.py   # LLM智能筛选模块
├── content_extractor.py  # 内容提取模块
├── email_sender.py       # 邮件发送模块
├── scheduler.py          # 定时任务调度器
└── main.py              # 主程序入口
```

## 🔧 故障排除

### 常见问题

#### 1. SGLang服务器启动失败
```bash
# 检查GPU支持
nvidia-smi

# 检查Docker GPU支持
docker run --rm --gpus all nvidia/cuda:11.0-base nvidia-smi
```

#### 2. 邮件发送失败
- 检查163邮箱是否开启SMTP服务
- 确认使用的是授权码而不是登录密码
- 检查网络连接和防火墙设置

#### 3. 容器启动失败
```bash
# 查看容器日志
docker logs qwen-sglang-server

# 清理并重新构建
./docker_manager.sh clean
./docker_manager.sh start
```

## 📈 性能优化

### GPU优化
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

### 内存优化
```yaml
# 调整SGLang服务器内存使用
environment:
  - GPU_MEMORY_UTILIZATION=0.8
  - MAX_MODEL_LEN=4096
```

## 🎯 更新日志

### 2025-09-10 重大更新

#### ✅ 新增功能
- **Docker智能管理**: 自动检查容器和镜像状态，智能启动服务
- **错误邮件通知**: 任务失败时自动发送详细错误信息
- **完整执行入口**: `quick_start.sh` 作为统一执行入口
- **163邮箱支持**: 完整的163邮箱SMTP配置和SSL连接支持

#### 🔧 修复问题
- 修复 `keywords.yaml` → `topics.yaml` 配置不一致问题
- 修复 `schedule` 模块导入问题
- 修复模型路径配置问题
- 移除已弃用的本地启动方法

#### 🧪 测试结果
- arXiv爬虫: 成功获取256篇论文
- 邮件发送: 163邮箱连接测试成功
- Docker构建: 镜像构建和容器创建成功

## 📞 支持

如有问题或建议，请通过以下方式联系：
- 邮件: ckx.ict@gmail.com
- 错误通知会自动发送到配置的邮箱

## 📄 许可证

本项目采用 MIT 许可证。