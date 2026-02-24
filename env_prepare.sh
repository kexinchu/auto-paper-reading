#!/usr/bin/env bash
# 环境准备脚本：创建 venv、安装依赖、从 ModelScope 下载模型到本地 Models 目录

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 可配置项（也可通过环境变量覆盖）
PORT="${MODEL_SERVER_PORT:-8000}"
MODEL_DIR="${MODEL_DIR:-$SCRIPT_DIR/Models/Qwen3-4B}"
CHECK_INTERVAL_MINUTES="${CHECK_INTERVAL_MINUTES:-109}"
PID_FILE="$SCRIPT_DIR/.model_server.pid"
LOG_FILE="$SCRIPT_DIR/model_server.log"

# 检测环境是否就绪：无 venv 则创建，有则直接激活
if [[ ! -d "$SCRIPT_DIR/venv" ]]; then
  echo "==> 创建 Python 虚拟环境 (venv) ..."
  python3 -m venv "$SCRIPT_DIR/venv"
  echo "==> 激活虚拟环境并安装依赖 ..."
  # shellcheck source=/dev/null
  source "$SCRIPT_DIR/venv/bin/activate"
  pip install --upgrade pip
  pip install -r requirements.txt
else
  echo "==> 虚拟环境已存在，跳过创建"
  source "$SCRIPT_DIR/venv/bin/activate"
fi


MODEL_LOCAL_DIR="$SCRIPT_DIR/Models/Qwen3-4B"
if [[ -d "$MODEL_LOCAL_DIR" ]] && [[ -n "$(ls -A "$MODEL_LOCAL_DIR" 2>/dev/null)" ]]; then
  echo "==> 模型目录已存在，跳过下载: $MODEL_LOCAL_DIR"
else
  pip install modelscope
  echo "==> 从 ModelScope 下载模型到 ./Models/Qwen3-4B ..."
  mkdir -p "$SCRIPT_DIR/Models"
  modelscope download --model Qwen/Qwen3-4B --local_dir "$MODEL_LOCAL_DIR"
fi

# 检测并初始化 SQLite 与存储目录（依赖 config/config.yaml）
if [[ -f "$SCRIPT_DIR/config/config.yaml" ]]; then
  if [[ -f "$SCRIPT_DIR/data/arxiv.db" ]]; then
    echo "==> SQLite 已存在: ./data/arxiv.db"
  else
    echo "==> 初始化 SQLite 与存储目录 ..."
    PYTHONPATH="$SCRIPT_DIR" python3 "$SCRIPT_DIR/tests/setup_storage_db.py"
  fi
else
  echo "==> 跳过 DB 初始化（未找到 config/config.yaml）"
fi

start_server() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 启动模型推理服务: $MODEL_DIR, 端口 $PORT"
  # 后台启动 vLLM OpenAI 兼容服务；日志追加到文件
  nohup python -u -m vllm.entrypoints.openai.api_server \
    --host 0.0.0.0 \
    --port "$PORT" \
    --model "$MODEL_DIR" \
    >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  echo "     PID: $(cat "$PID_FILE")，日志: $LOG_FILE"
}

stop_server() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] 停止模型推理服务 (PID=$pid)"
      kill "$pid" 2>/dev/null || true
      sleep 2
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi
}

# vLLM 提供 /health，健康时返回 200
check_health() {
  curl -sf -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/health" 2>/dev/null || echo "000"
}

restart_if_needed() {
  local code
  code=$(check_health)
  if [[ "$code" != "200" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 健康检查失败 (HTTP $code)，重启服务"
    stop_server
    sleep 3
    start_server
    # 等待服务就绪
    for i in {1..60}; do
      sleep 5
      code=$(check_health)
      if [[ "$code" == "200" ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 服务已就绪"
        return
      fi
    done
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 警告: 启动后仍未就绪，请查看 $LOG_FILE"
  fi
}

# 首次启动
start_server

echo "==> 本地 API 已启动"
echo "     base_url: http://127.0.0.1:$PORT/v1"
echo "     模型列表: http://127.0.0.1:$PORT/v1/models"
echo "     健康检查: http://127.0.0.1:$PORT/health"
echo "==> 每 ${CHECK_INTERVAL_MINUTES} 分钟检测一次可用性，不可用时自动重启"
echo ""

# 每 109 分钟检测一次，不可用则重启
while true; do
  sleep $((CHECK_INTERVAL_MINUTES * 60))
  restart_if_needed
done
