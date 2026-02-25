#!/usr/bin/env bash
# 定时执行 pipeline：先确保 LLM 服务可用，再执行；失败则每小时重试直至成功。
# 用法：本脚本单次运行“确保 LLM + 执行 pipeline”；由 crontab 每天 8 点触发，例如：
#   mkdir -p /path/to/auto-paper-reading/logs
#   0 8 * * * /path/to/auto-paper-reading/run.sh >> /path/to/auto-paper-reading/logs/run.log 2>&1
# 可选环境变量：RUN_CONFIG, RUN_TOPICS, MODEL_SERVER_PORT=8000, RETRY_INTERVAL_SEC=3600, HEALTH_WAIT_MAX_SEC=600

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG="${RUN_CONFIG:-config/config_kexin.yaml}"
TOPICS="${RUN_TOPICS:-config/topics.yaml}"
PORT="${MODEL_SERVER_PORT:-8000}"
RETRY_INTERVAL_SEC="${RETRY_INTERVAL_SEC:-3600}"
HEALTH_WAIT_MAX_SEC="${HEALTH_WAIT_MAX_SEC:-600}"
HEALTH_POLL_SEC="${HEALTH_POLL_SEC:-15}"
PID_FILE="$SCRIPT_DIR/logs/model_server.pid"
ENV_PREPARE_PID_FILE="$SCRIPT_DIR/logs/run_env_prepare.pid"

health_ok() {
  curl -sf -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q 200
}

ensure_llm() {
  if health_ok; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] LLM 服务已可用 (port $PORT)"
    return 0
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] LLM 不可用，启动 env_prepare.sh ..."
  nohup bash "$SCRIPT_DIR/env_prepare.sh" >> "$SCRIPT_DIR/logs/env_prepare_run.log" 2>&1 &
  echo $! > "$ENV_PREPARE_PID_FILE"
  local waited=0
  while (( waited < HEALTH_WAIT_MAX_SEC )); do
    sleep "$HEALTH_POLL_SEC"
    (( waited += HEALTH_POLL_SEC )) || true
    if health_ok; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] LLM 服务已就绪 (等待 ${waited}s)"
      return 0
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 等待 LLM 就绪 ... ${waited}s / ${HEALTH_WAIT_MAX_SEC}s"
  done
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 等待 LLM 超时，本次将尝试执行 pipeline"
  return 1
}

run_pipeline() {
  export PYTHONPATH="$SCRIPT_DIR"
  # 使用项目 venv 若存在
  if [[ -d "$SCRIPT_DIR/venv" ]]; then
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/venv/bin/activate"
  fi
  python3 -m src --config "$SCRIPT_DIR/$CONFIG" --topics "$SCRIPT_DIR/$TOPICS"
}

# 清理本次下载的 PDF 文件（与 config storage.pdf_dir 一致）
PDF_DIR="${PDF_DIR:-$SCRIPT_DIR/data/pdfs}"

clear_downloaded_pdfs() {
  if [[ -d "$PDF_DIR" ]]; then
    local n
    n=$(find "$PDF_DIR" -maxdepth 1 -type f -name "*.pdf" 2>/dev/null | wc -l)
    if [[ "${n:-0}" -gt 0 ]]; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] 清理下载的 PDF: $PDF_DIR ($n 个文件)"
      find "$PDF_DIR" -maxdepth 1 -type f -name "*.pdf" -delete 2>/dev/null || true
    fi
  fi
}

# 成功退出前：关闭 LLM 服务及本次启动的 env_prepare，释放 GPU
stop_llm_and_env_prepare() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid=$(cat "$PID_FILE" 2>/dev/null)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] 关闭 LLM 服务 (PID=$pid)，释放 GPU"
      kill "$pid" 2>/dev/null || true
      sleep 2
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi
  if [[ -f "$ENV_PREPARE_PID_FILE" ]]; then
    local ep_pid
    ep_pid=$(cat "$ENV_PREPARE_PID_FILE" 2>/dev/null)
    if [[ -n "$ep_pid" ]] && kill -0 "$ep_pid" 2>/dev/null; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] 关闭 env_prepare.sh (PID=$ep_pid)"
      kill "$ep_pid" 2>/dev/null || true
      sleep 1
      kill -9 "$ep_pid" 2>/dev/null || true
    fi
    rm -f "$ENV_PREPARE_PID_FILE"
  fi
}

echo "========== run.sh 开始 =========="
while true; do
  ensure_llm || true
  if run_pipeline; then
    stop_llm_and_env_prepare
    clear_downloaded_pdfs
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] pipeline 执行成功，已关闭 LLM、清理 PDF，退出"
    exit 0
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] pipeline 未完全成功，${RETRY_INTERVAL_SEC}s 后重试"
  sleep "$RETRY_INTERVAL_SEC"
done
