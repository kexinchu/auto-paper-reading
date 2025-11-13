# 自动论文阅读工具

基于OpenAI兼容API的智能论文筛选和阅读工具，自动从arXiv获取论文，使用大语言模型进行智能筛选和内容提取，并通过邮件发送摘要。

## 主要特性

- **三级智能筛选**：
  - 🔍 **关键词预筛选**：快速过滤明显不相关的论文
  - 🎯 **相关性评估**：LLM判断论文与主题的相关程度（0-10分）
  - ⭐ **质量评估**：LLM评估论文的学术质量和创新性（0-10分）
- **灵活配置**：支持为每个主题配置关键词和详细描述
- **内容提取**：自动下载PDF并提取核心内容
- **多API支持**：支持OpenAI、DeepSeek、通义千问、硅基流动等多种API
- **定时任务**：支持定时执行，每日自动推送
- **邮件通知**：将筛选结果和摘要发送到邮箱
- **Docker支持**：提供完整的Docker部署方案

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API密钥

在 `config.yaml` 中配置LLM API：

```yaml
llm:
  api_base: "https://api.deepseek.com"  # 或其他OpenAI兼容API
  api_key: "YOUR_API_KEY_HERE"  # 你的API密钥
  model: "deepseek-chat"  # 模型名称
```

或通过环境变量设置：

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_API_BASE="https://api.deepseek.com"
export OPENAI_MODEL="deepseek-chat"
```

### 3. 配置论文主题

编辑 `topics.yaml`，添加你感兴趣的研究主题：

```yaml
topics:
  - name: "大语言模型优化"
    description: "关注大语言模型的训练和推理优化，包括KV-Cache优化、量化、剪枝等技术"
    keywords:  # 关键词列表，用于预筛选
      - "LLM"
      - "large language model"
      - "transformer"
      - "KV cache"
      - "quantization"
      - "inference optimization"
    # required_keywords:  # 可选：必须包含的关键词
    #   - "optimization"
  
  - name: "AI安全"
    description: "关注人工智能安全相关研究，包括对抗攻击、模型安全性评估等"
    keywords:
      - "AI safety"
      - "adversarial attack"
      - "security"
      - "robustness"

# 筛选配置
filtering:
  keyword_match_threshold: 0.1  # 关键词匹配阈值（0-1）
  min_relevance_score: 6  # LLM相关性评分阈值（0-10）
  min_quality_score: 6  # LLM质量评分阈值（0-10）
  enable_quality_assessment: true  # 是否启用质量评估
```

### 4. 配置邮件

在 `config.yaml` 中配置邮件发送：

```yaml
email:
  smtp_server: "smtp.163.com"
  smtp_port: 465
  sender_email: "your-email@163.com"
  sender_password: "your-password-or-auth-code"
  recipient_email: "recipient@gmail.com"
```

### 5. 运行

立即执行一次：
```bash
python main.py --run-now
```

测试所有组件：
```bash
python main.py --test
```

启动定时任务：
```bash
python main.py
```

## 使用Docker部署

### 1. 创建 `.env` 文件

```bash
OPENAI_API_KEY=your-api-key
OPENAI_API_BASE=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat
```

### 2. 启动服务

```bash
docker-compose up -d
```

### 3. 查看日志

```bash
docker-compose logs -f
```

### 4. 停止服务

```bash
docker-compose down
```

## 支持的API提供商

### 1. OpenAI（官方）
```yaml
llm:
  api_base: "https://api.openai.com/v1"
  api_key: "sk-..."
  model: "gpt-3.5-turbo"  # 或 gpt-4o-mini
```

### 2. DeepSeek（推荐，价格便宜）
```yaml
llm:
  api_base: "https://api.deepseek.com"
  api_key: "sk-..."
  model: "deepseek-chat"
```
注册地址：https://platform.deepseek.com/

### 3. 硅基流动 SiliconFlow（免费额度）
```yaml
llm:
  api_base: "https://api.siliconflow.cn/v1"
  api_key: "sk-..."
  model: "Qwen/Qwen2.5-7B-Instruct"
```
注册地址：https://siliconflow.cn/

### 4. 通义千问（阿里云）
```yaml
llm:
  api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "sk-..."
  model: "qwen-plus"  # 或 qwen-turbo
```
注册地址：https://dashscope.aliyun.com/

### 5. 其他OpenAI兼容API
任何支持OpenAI API格式的服务都可以使用。

## 配置说明

### config.yaml

```yaml
# LLM API配置
llm:
  api_base: "https://api.deepseek.com"
  api_key: "YOUR_API_KEY_HERE"
  model: "deepseek-chat"
  temperature: 0.1
  max_tokens: 500
  max_retries: 3
  retry_delay: 1
  timeout: 30

# arXiv配置
arxiv:
  categories: ["cs.AI", "cs.LG", "cs.CV"]
  batch_size: 50
  days_back: 1
  max_total_papers: 500

# 筛选配置
filtering:
  min_score: 6  # LLM评分阈值（0-10）
  max_papers_per_batch: 50

# PDF处理配置
pdf:
  auto_delete: true
  max_pdf_size_mb: 50
  extract_pages: 5

# 定时任务配置
schedule:
  time: "22:30"
  timezone: "America/New_York"
  enable_scheduler: true
```

### topics.yaml

```yaml
topics:
  - name: "主题名称"
    description: "详细的主题描述，用于LLM判断论文相关性"
```

## 命令行选项

```bash
python main.py [选项]

选项：
  --config CONFIG     配置文件路径（默认：config.yaml）
  --test              测试所有组件
  --run-now           立即执行一次任务
  --daemon            后台运行模式
  --timezone TZ       指定时区（如：America/New_York）
```

## 工作流程

### 三级筛选机制 + 智能全文判断

本工具采用**关键词预筛选 + LLM智能评估 + 全文需求判断**的机制，既保证效率又保证质量：

```
论文池 (500篇)
    ↓
【第一级】关键词预筛选
    - 快速匹配标题和摘要中的关键词
    - 过滤明显不相关的论文
    - 节省API调用成本（免费）
    ↓
候选论文 (~100篇)
    ↓
【第二级】LLM相关性评估
    - 评估论文与主题的相关程度（0-10分）
    - 判断是否解决主题相关问题
    - 给出相关性理由
    ↓
相关论文 (~30篇)
    ↓
【第三级】LLM质量评估 + 全文需求判断
    - 评估论文的学术质量和创新性（0-10分）
    - 考察创新性、方法可靠性、实验充分性
    - 🔍 智能判断：是否需要下载全文？
      • 需要全文：摘要信息不足，技术细节需深入了解
      • 仅摘要：摘要已足够清楚，或质量一般
    - 给出质量评价理由
    ↓
高质量论文 (~10篇)
├─ 📄 需要全文 (~3篇) → 下载PDF → 深度提取
└─ 📋 仅摘要 (~7篇) → 直接提取摘要
    ↓
内容提取 → 邮件推送
```

**优势**：
- ⚡ 节省下载时间：只下载真正需要的PDF
- 💰 节省成本：减少PDF处理的token消耗
- 🎯 精准判断：LLM智能评估哪些论文需要深入阅读

### 完整流程

1. **论文获取**：从arXiv API获取最新论文（支持多个领域）
2. **关键词筛选**：使用配置的关键词快速过滤不相关论文
3. **相关性评估**：LLM评估论文与主题的相关程度（0-10分）
4. **质量评估 + 全文判断**：
   - LLM评估论文的学术质量和创新性（0-10分）
   - 🆕 **智能判断是否需要下载全文**（节省下载和处理成本）
5. **综合评分**：计算加权得分，保留高质量论文
6. **选择性PDF下载**：🆕 **仅下载标记为"需要全文"的论文**
7. **内容提取**：
   - 需要全文：从PDF提取详细内容
   - 仅摘要：直接从摘要提取核心信息
8. **邮件发送**：将提取的内容格式化后发送到邮箱
9. **清理**：自动删除下载的PDF文件

## 项目结构

```
.
├── main.py                  # 主程序入口
├── scheduler.py             # 定时任务调度器
├── arxiv_crawler.py         # arXiv论文爬虫
├── llm_paper_filter.py      # LLM智能筛选器
├── content_extractor.py     # 内容提取器
├── email_sender.py          # 邮件发送器
├── config.yaml              # 应用配置
├── topics.yaml              # 论文主题配置
├── requirements.txt         # Python依赖
├── Dockerfile               # Docker镜像
└── docker-compose.yml       # Docker Compose配置
```

## 故障排除

### 1. API连接失败
- 检查API密钥是否正确
- 检查网络连接
- 确认API服务商额度是否充足

### 2. 论文筛选效果不佳
- **关键词配置**：在 `topics.yaml` 中添加更多相关关键词
- **主题描述优化**：提供更详细、更具体的主题描述
- **调整阈值**：
  - `keyword_match_threshold`: 降低以包含更多论文（如0.05）
  - `min_relevance_score`: 提高以只保留高度相关论文（如7-8分）
  - `min_quality_score`: 提高以只保留高质量论文（如7-8分）
- **模型选择**：尝试更强大的模型（如gpt-4o-mini效果更好）
- **关闭质量评估**：如果只关心相关性，设置 `enable_quality_assessment: false`

### 3. 邮件发送失败
- 确认SMTP服务器设置正确
- 检查是否使用授权码（而非登录密码）
- 检查防火墙是否阻止SMTP端口

### 4. PDF下载失败
- 增大 `max_pdf_size_mb` 限制
- 检查网络连接
- 系统会自动回退到仅使用摘要

## 优势

- **无需GPU**：使用云端API，无需本地GPU
- **低成本**：多个免费或低价API可选（如DeepSeek仅￥0.001/千tokens）
- **易部署**：无需下载大型模型文件
- **高质量**：使用最新的大语言模型，效果优秀
- **灵活配置**：支持多种API提供商，随时切换

## 成本估算

以DeepSeek为例（￥0.001/千tokens输入，￥0.002/千tokens输出）：

### 最新优化方案（v2.1 - 智能全文判断）
- **关键词筛选**：500篇 → 100篇（无成本）
- **相关性评估**：100篇 × 约1500 tokens → ￥0.15
- **质量评估 + 全文判断**：30篇 × 约1500 tokens → ￥0.045
- **内容提取**：
  - 📄 需要全文（3篇）：3 × 约5000 tokens → ￥0.03
  - 📋 仅摘要（7篇）：7 × 约1500 tokens → ￥0.02
- **每天总成本**：约￥0.25/天 → **￥7.5/月**

### 方案对比

| 方案 | PDF下载 | 内容提取成本 | 总成本/月 | 节省 |
|------|---------|-------------|----------|------|
| v1.0（全部下载PDF） | 10篇 | ￥0.15 | ￥10/月 | - |
| v2.0（全部下载PDF） | 10篇 | ￥0.15 | ￥8/月 | 20% |
| **v2.1（智能选择）** | **3篇** | **￥0.05** | **￥7.5/月** | **25%** |

### 优化效果
- 🎯 **PDF下载量减少70%**：从10篇降至3篇
- ⚡ **处理时间减少60%**：PDF处理最耗时
- 💰 **成本降低6%**：额外节省约￥0.5/月
- 📊 **质量不降反升**：只深入阅读真正值得的论文

### 成本优化建议
1. **优化关键词**：提高预筛选准确性，减少LLM调用
2. **调整阈值**：提高质量阈值，减少需要处理的论文数
3. **使用免费API**：硅基流动提供免费额度
4. **关闭质量评估**（不推荐）：失去全文智能判断功能

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！

## 联系方式

如有问题，请提交Issue或联系开发者。
