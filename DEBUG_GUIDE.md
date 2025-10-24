# 调试指南

## 调试流程

### 1. 启动调试环境
```bash
./debug.sh --start
```

### 2. 进入调试容器
```bash
./debug.sh --enter
```

### 3. 在容器内进行调试

#### 3.1 检查基础环境
```bash
# 检查Python版本
python --version

# 检查已安装的包
pip list

# 检查GPU可用性
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

#### 3.2 测试SGLang安装
```bash
# 测试SGLang导入
python -c "import sglang; print('SGLang导入成功')"

# 检查SGLang版本
python -c "import sglang; print(f'SGLang版本: {sglang.__version__}')"
```

#### 3.3 测试SGLang启动命令
```bash
# 测试SGLang启动命令（不实际启动）
python -m sglang.launch_server --help

# 如果出现错误，记录错误信息
```

#### 3.4 安装缺失的依赖
```bash
# 如果遇到缺失的包，安装它们
pip install <package_name>

# 记录所有安装的包
pip freeze > /app/debug_logs/installed_packages.txt
```

#### 3.5 测试完整启动
```bash
# 测试SGLang完整启动（在后台）
python -m sglang.launch_server \
    --model-path /app/models/Qwen3-0.6B \
    --host 0.0.0.0 \
    --port 8089 \
    --trust-remote-code \
    --attention-backend flashinfer \
    --decode-attention-backend flashinfer \
    --disable-cuda-graph \
    --mem-fraction-static 0.8 \
    --max-running-requests 32 \
    --max-queued-requests 64 &

# 等待几秒后检查服务
sleep 10
curl -f http://localhost:8089/health || echo "服务未启动"
```

### 4. 记录问题和解决方案

#### 4.1 创建问题记录文件
```bash
# 在容器内创建问题记录
cat > /app/debug_logs/issues.md << 'EOF'
# 调试问题记录

## 遇到的问题

### 问题1: 缺失依赖
- 错误信息: ModuleNotFoundError: No module named 'xxx'
- 解决方案: pip install xxx
- 状态: 已解决

### 问题2: 启动失败
- 错误信息: [具体错误]
- 解决方案: [具体解决方案]
- 状态: 待解决

## 已安装的额外包
- package1
- package2
- ...

## 最终可用的启动命令
```bash
python -m sglang.launch_server [参数]
```
EOF
```

#### 4.2 记录环境配置
```bash
# 记录环境变量
env > /app/debug_logs/environment.txt

# 记录Python路径
which python > /app/debug_logs/python_path.txt

# 记录已安装包
pip freeze > /app/debug_logs/requirements_final.txt
```

### 5. 退出调试容器
```bash
exit
```

### 6. 停止调试环境
```bash
./debug.sh --stop
```

### 7. 更新配置文件

根据调试结果更新以下文件：
- `requirements.txt` - 添加所有需要的依赖
- `Dockerfile` - 更新启动命令和环境配置
- `docker-compose.yml` - 更新环境变量

## 调试技巧

1. **分步测试**: 先测试导入，再测试启动
2. **记录一切**: 记录所有错误和解决方案
3. **验证环境**: 确保所有依赖都正确安装
4. **测试完整流程**: 确保从启动到服务就绪的完整流程

## 常见问题

### 依赖问题
- 使用 `pip install` 安装缺失的包
- 记录包名和版本号

### 环境变量问题
- 检查CUDA相关环境变量
- 检查SGLang相关环境变量

### 启动参数问题
- 测试不同的启动参数组合
- 记录有效的参数配置
