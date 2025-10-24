# 单容器论文阅读工具

基于SGLang 0.4.7的单容器架构，在一个容器中完成LLM服务和论文阅读处理。

## 架构特点

- **单容器架构**：所有服务运行在一个容器中
- **SGLang 0.4.7**：使用最新版本的SGLang进行LLM服务
- **GPU加速**：支持NVIDIA GPU加速推理
- **自动管理**：自动启动SGLang服务和论文处理

## 快速开始

### 1. 启动服务
```bash
./start.sh --run
```

### 2. 测试服务
```bash
./start.sh --test
```

### 3. 查看状态
```bash
./start.sh --status
```

### 4. 查看日志
```bash
./start.sh --logs
```

### 5. 进入容器调试
```bash
./start.sh --debug
```

### 6. 进入容器shell
```bash
./start.sh --shell
```

### 7. 停止服务
```bash
./start.sh --stop
```

## 服务管理

| 命令 | 功能 |
|------|------|
| `./start.sh --run` | 启动完整任务 |
| `./start.sh --test` | 测试所有组件 |
| `./start.sh --stop` | 停止服务 |
| `./start.sh --restart` | 重启服务 |
| `./start.sh --logs` | 查看日志 |
| `./start.sh --status` | 查看状态 |
| `./start.sh --debug` | 进入容器调试 |
| `./start.sh --shell` | 进入容器shell |

## 技术架构

- **容器**: 基于Python 3.10-slim
- **LLM服务**: SGLang 0.4.7
- **模型**: Qwen3-0.6B
- **GPU**: 支持NVIDIA GPU加速
- **端口**: 8089 (SGLang服务)

## 配置说明

- `config.yaml`: 应用配置
- `topics.yaml`: 论文主题配置
- 模型路径: `/app/models/Qwen3-0.6B`
- 日志目录: `./logs`
- 下载目录: `./downloads`

## 故障排除

1. **容器启动失败**: 检查Docker和GPU驱动
2. **SGLang服务未响应**: 查看日志 `./start.sh --logs`
3. **GPU内存不足**: 调整`--mem-fraction-static`参数
4. **模型加载失败**: 检查模型路径和权限

## 优势

- **简化部署**: 单容器架构，易于管理
- **资源高效**: 共享GPU内存和计算资源
- **自动恢复**: 容器自动重启和健康检查
- **统一日志**: 所有服务日志集中管理
- **智能管理**: 自动检测现有容器/镜像，避免重复构建
- **调试友好**: 支持容器内调试和shell访问

## 智能资源管理

系统会自动检测现有资源，按以下优先级启动：

1. **运行中的容器**: 直接使用现有容器
2. **停止的容器**: 启动现有容器
3. **现有镜像**: 使用现有镜像创建新容器
4. **无现有资源**: 构建新镜像

这避免了不必要的镜像重建，节省时间和存储空间。
