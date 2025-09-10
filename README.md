# 自动论文阅读工具

一个本地运行的智能论文阅读工具，能够自动从arXiv获取最新论文，根据关键词筛选相关内容，使用Qwen模型提取核心信息，并通过邮件定时发送摘要。

## 功能特性

- 🔍 **自动爬取**: 从arXiv获取最新的学术论文
- 🎯 **智能筛选**: 基于关键词和语义匹配筛选相关论文
- 🤖 **AI提取**: 使用SGLang + Qwen2.5-0.5B模型提取论文核心内容
- 📧 **邮件推送**: 定时发送格式化的论文摘要邮件
- ⏰ **定时任务**: 支持自定义时间自动执行
- 📊 **多模式匹配**: 支持精确匹配、模糊匹配和语义匹配
- 🐳 **Docker部署**: 支持容器化部署，易于扩展和维护
- 🚀 **高性能**: 基于SGLang框架，支持GPU加速和并发处理

## 安装说明

### 方式一：Docker部署（推荐）

#### 1. 系统要求

##### 硬件要求
- **GPU**: NVIDIA GPU (推荐RTX 3080或更高)
- **内存**: 至少16GB RAM
- **存储**: 至少50GB可用空间
- **CPU**: 4核心以上

##### 软件要求
- Docker 20.10+
- Docker Compose 2.0+
- NVIDIA Container Toolkit (用于GPU支持)
- nvidia-docker2 (可选，推荐)

#### 2. 安装NVIDIA Container Toolkit

##### Ubuntu/Debian
```bash
# 添加NVIDIA包仓库
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

# 安装nvidia-docker2
sudo apt-get update && sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker
```

##### CentOS/RHEL
```bash
# 添加NVIDIA包仓库
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.repo | sudo tee /etc/yum.repos.d/nvidia-docker.repo

# 安装nvidia-docker2
sudo yum install -y nvidia-docker2
sudo systemctl restart docker
```

#### 3. 快速部署
```bash
# 克隆项目
git clone <your-repo-url>
cd auto-paper-reading

# 运行部署脚本
chmod +x deploy.sh
./deploy.sh
```

#### 4. 手动部署
```bash
# 构建并启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 方式二：本地安装

#### 1. 环境要求
- Python 3.8+
- CUDA支持（可选，用于GPU加速）

#### 2. 安装依赖
```bash
pip install -r requirements.txt
```

### 3. 配置设置

#### 3.1 邮件配置

编辑 `config.yaml` 文件中的邮件配置：

```yaml
email:
  smtp_server: "smtp.gmail.com"  # 你的邮箱SMTP服务器
  smtp_port: 587
  sender_email: "your_email@gmail.com"  # 你的邮箱
  sender_password: "your_app_password"  # 你的应用密码
  recipient_email: "your_email@gmail.com"  # 接收邮箱
```

**重要**: 对于Gmail，需要使用应用专用密码，不是你的登录密码。

#### 3.2 主题配置

编辑 `topics.yaml` 文件，使用自然语言描述你感兴趣的研究主题：

```yaml
topics:
  - name: "Machine Learning & LLM"
    description: "Machine learning and large language model research, including transformer architectures, attention mechanisms, mixture of experts (MoE), diffusion models, foundation models, model pruning, quantization techniques, and KV cache optimization for efficient inference."
  
  - name: "Computer Systems"
    description: "Computer systems research focusing on memory technologies, including CXL (Compute Express Link) memory interconnects, RDMA (Remote Direct Memory Access) for high-performance computing, and advanced memory management techniques."
  
  - name: "Multimodal & Agents"
    description: "Multimodal learning and multi-agent systems research, including multi-modality approaches, multi-task learning, multi-agent coordination, security in AI systems, approximate nearest neighbor search (ANNS), and out-of-distribution detection and handling."
```

#### 3.3 模型配置

在 `config.yaml` 中配置SGLang服务器：

```yaml
model:
  sglang_server_url: "http://localhost:30000"  # SGLang服务器地址
  max_length: 2048
  temperature: 0.7
  max_retries: 3
  retry_delay: 1
```

#### 3.4 其他配置

在 `config.yaml` 中可以调整：

- arXiv学科分类
- 筛选阈值
- 定时任务时间

## 测试和验证

### 测试Gmail配置
```bash
# 测试Gmail连接和发送
python3 test_gmail.py
```

### 测试LLM智能筛选
```bash
# 测试LLM筛选功能（需要SGLang服务器运行）
python3 test_llm_filter.py
```

### 测试Gmail配置
```bash
# 测试Gmail连接和发送
python3 test_gmail.py
```

### 测试基础组件
```bash
# 测试arXiv爬虫
python3 -c "
from arxiv_crawler import ArxivCrawler
import yaml

with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

crawler = ArxivCrawler(config['arxiv'])
papers = crawler.get_all_recent_papers()
print(f'获取到 {len(papers)} 篇论文')
"
```

## 使用方法

### 🚀 一键启动（推荐）

```bash
# 快速启动（自动检测环境）
./quick_start.sh

# 或者使用完整脚本
./run_paper_reader.sh --local    # 本地运行
./run_paper_reader.sh --docker   # Docker运行
./run_paper_reader.sh --test     # 测试组件
./run_paper_reader.sh --run-now  # 立即执行
```

### Docker部署方式

#### 1. 配置环境

##### 1.1 配置邮件设置
编辑 `config.yaml`:
```yaml
email:
  smtp_server: "smtp.gmail.com"
  smtp_port: 587
  sender_email: "ckx.ict@gmail.com"
  sender_password: "your_app_password"
  recipient_email: "ckx.ict@gmail.com"
```

##### 1.2 配置关键词
编辑 `topics.yaml` 添加你感兴趣的topic。

##### 1.3 配置模型参数
在 `config.yaml` 中调整模型配置:
```yaml
model:
  name: "/app/models/Qwen2.5-0.5B-Instruct"  # 本地模型路径
  sglang_server_url: "http://sglang-server:30000"
  max_length: 2048
  temperature: 0.7
  max_retries: 3
  retry_delay: 1
```

#### 2. 构建和启动服务

##### 2.1 使用Docker Compose (推荐)
```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

##### 2.2 单独启动SGLang服务器
```bash
# 启动SGLang服务器
docker run -d \
  --name qwen-sglang-server \
  --gpus all \
  -p 30000:30000 \
  -v /home/kec23008/docker-sys/llm-security/Models:/app/models \
  auto-paper-reading \
  python sglang_server.py
```

#### 3. 验证部署

##### 3.1 检查服务状态
```bash
# 检查容器状态
docker-compose ps

# 检查SGLang服务器健康状态
curl http://localhost:30000/health
```

##### 3.2 测试API
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

##### 3.3 测试完整流程
```bash
# 进入容器测试
docker-compose exec paper-reader python main.py --test
```

#### 4. 服务管理

##### 4.1 测试组件
```bash
docker-compose exec paper-reader python main.py --test
```

##### 4.2 立即执行一次任务
```bash
docker-compose exec paper-reader python main.py --run-now
```

##### 4.3 查看服务状态
```bash
docker-compose ps
docker-compose logs -f
```

##### 4.4 重启服务
```bash
docker-compose restart
```

#### 5. 监控和维护

##### 5.1 查看日志
```bash
# 查看所有服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f sglang-server
docker-compose logs -f paper-reader
```

##### 5.2 重启服务
```bash
# 重启所有服务
docker-compose restart

# 重启特定服务
docker-compose restart sglang-server
```

##### 5.3 更新服务
```bash
# 重新构建并启动
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

##### 5.4 清理资源
```bash
# 停止并删除容器
docker-compose down

# 删除镜像
docker-compose down --rmi all

# 清理未使用的资源
docker system prune -a
```

### 本地安装方式

#### 1. 安装依赖
```bash
./run_paper_reader.sh --setup
```

#### 2. 测试组件
```bash
python main.py --test
```

#### 3. 立即执行一次任务
```bash
python main.py --run-now
```

#### 4. 启动定时任务
```bash
python main.py
```

程序将按照配置的时间（纽约时间22:30）每天自动执行。

## 项目结构

```
auto-paper-reading/
├── arxiv_crawler.py          # arXiv论文爬取模块（支持分批处理）
├── llm_paper_filter.py       # LLM智能筛选模块
├── content_extractor.py      # 内容提取模块（支持PDF处理）
├── email_sender.py           # 邮件发送模块
├── scheduler.py              # 定时任务调度器（纽约时间）
├── main.py                   # 主程序入口
├── sglang_server.py          # SGLang服务器启动脚本
├── run_paper_reader.sh       # 一键运行脚本
├── quick_start.sh            # 快速启动脚本
├── deploy.sh                 # Docker部署脚本
├── config.yaml               # 主配置文件
├── topics.yaml               # 智能主题配置文件
├── requirements.txt          # 依赖包列表
├── Dockerfile                # Docker镜像构建文件
├── docker-compose.yml        # Docker Compose配置
├── docker-compose.prod.yml   # 生产环境配置
└── README.md                 # 说明文档
```

## 配置说明

### arXiv配置

```yaml
arxiv:
  categories: ["cs.AI", "cs.LG", "cs.CV", "cs.CL", "cs.NE"]  # 学科分类
  batch_size: 50  # 每批处理的论文数量
  days_back: 1    # 获取最近几天的论文
  max_total_papers: 200  # 每天最多获取的论文总数
```

### 模型配置

```yaml
model:
  name: "Qwen/Qwen3-0.6B-Instruct"  # 模型名称
  sglang_server_url: "http://localhost:30000"  # SGLang服务器地址
  max_context_length: 32768  # 最大上下文长度
  max_generation_length: 2048  # 最大生成长度
  temperature: 0.7  # 生成温度
  max_retries: 3  # 最大重试次数
  retry_delay: 1  # 重试延迟（秒）
  download_from_huggingface: true  # 从HuggingFace下载模型
```

### 筛选配置

```yaml
filtering:
  min_score: 0.3  # 最小匹配分数
  max_papers_per_batch: 10  # 每批最多处理的论文数量
  enable_deduplication: true  # 启用去重
```

### PDF处理配置

```yaml
pdf:
  auto_delete: true  # 处理完成后自动删除PDF
  max_pdf_size_mb: 50  # 最大PDF文件大小(MB)
  extract_pages: 5  # 最多提取PDF前几页
```

### 定时任务配置

```yaml
schedule:
  time: "22:30"  # 每天运行时间（纽约时间）
  timezone: "America/New_York"  # 时区
  enable_scheduler: true  # 是否启用定时任务
```

## 邮件配置指南

### Gmail配置

1. 启用两步验证
2. 生成应用专用密码
3. 使用应用密码作为 `sender_password`

### 其他邮箱配置

- **163邮箱**: smtp.163.com:25
- **QQ邮箱**: smtp.qq.com:587
- **Outlook**: smtp-mail.outlook.com:587

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

#### 2. 模型加载失败
```bash
# 检查模型路径
ls -la /home/kec23008/docker-sys/llm-security/Models/

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

## 常见问题

### Q: 模型下载失败怎么办？

A: 确保网络连接正常，或者手动下载模型到本地目录 `/home/kec23008/docker-sys/llm-security/Models/`。

### Q: 邮件发送失败？

A: 检查邮件配置，确保使用正确的SMTP服务器和应用密码。对于Gmail，需要使用应用专用密码。

### Q: 如何调整筛选精度？

A: 修改 `topics.yaml` 中的匹配模式和阈值设置。

### Q: 如何添加新的关键词？

A: 编辑 `topics.yaml` 文件，在相应的分类下添加关键词。

### Q: Docker容器启动失败？

A: 检查GPU驱动和NVIDIA Container Toolkit是否正确安装，确保模型路径映射正确。

## 日志文件

程序运行时会生成 `paper_reader.log` 日志文件，记录详细的执行信息。

## 注意事项

1. 首次运行会下载Qwen模型，需要较长时间
2. 建议在服务器上运行，确保网络稳定
3. 定期检查日志文件，确保程序正常运行
4. 注意arXiv的访问频率限制

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request来改进这个项目。