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

SELF_USER="kec23008"
GPU_WAIT_SEC="${GPU_WAIT_SEC:-21600}"     # 等他人释放 GPU 的等待时间，默认 6h
GPU_WAIT_MAX_RETRIES="${GPU_WAIT_MAX_RETRIES:-3}"  # 等他人最多重试次数，超出则放弃当天任务

health_ok() {
  curl -sf -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/health" 2>/dev/null | grep -q 200
}

# 返回 GPU 0 上占用显存的进程 PID 列表（排除自身 shell 等微小占用）
gpu0_pids() {
  nvidia-smi --query-compute-apps=pid,used_gpu_memory \
    --format=csv,noheader --id=0 2>/dev/null \
    | awk -F',' '{gsub(/ /,"",$2); if ($2+0 > 100) print $1+0}'
}

# 等待 GPU 0 空闲，必要时杀掉属于自己的残留进程
# 若被其他用户占用则每隔 GPU_WAIT_SEC 秒重试，超过 GPU_WAIT_MAX_RETRIES 次则返回 1（放弃当天任务）
wait_gpu_free() {
  local other_retries=0
  while true; do
    local pids
    pids=$(gpu0_pids)
    [[ -z "$pids" ]] && return 0   # GPU 已空闲

    local other_user_found=0
    for pid in $pids; do
      local owner
      owner=$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')
      [[ -z "$owner" ]] && continue   # 进程已消失，忽略
      if [[ "$owner" == "$SELF_USER" ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU 0 被本用户残留进程占用 (PID=$pid)，正在 kill ..."
        kill "$pid" 2>/dev/null || true
        sleep 3
        kill -9 "$pid" 2>/dev/null || true
      else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU 0 被其他用户 ($owner, PID=$pid) 占用"
        other_user_found=1
      fi
    done

    if [[ "$other_user_found" -eq 1 ]]; then
      (( other_retries++ )) || true
      if (( other_retries > GPU_WAIT_MAX_RETRIES )); then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU 0 等待他人释放已重试 ${GPU_WAIT_MAX_RETRIES} 次，放弃当天任务"
        return 1
      fi
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] 等待 ${GPU_WAIT_SEC}s 后重试 (${other_retries}/${GPU_WAIT_MAX_RETRIES}) ..."
      sleep "$GPU_WAIT_SEC"
    else
      # 只有自己的进程，杀完后稍等让显存释放
      sleep 5
    fi
  done
}

ensure_llm() {
  if health_ok; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] LLM 服务已可用 (port $PORT)"
    return 0
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] LLM 不可用，检查 GPU 0 占用 ..."
  wait_gpu_free || return 2   # 2 = GPU 被他人长期占用，放弃
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU 0 空闲，启动 env_prepare.sh ..."
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
  # 1) 按 PID 文件杀 vLLM 进程
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

  # 2) 若端口仍被占用，按端口杀进程（避免 PID 文件缺失或 vLLM 非本脚本启动时未释放 GPU）
  local port_pids
  port_pids=$(lsof -ti ":$PORT" 2>/dev/null || true)
  if [[ -n "$port_pids" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 发现端口 $PORT 仍被占用 (PID: $port_pids)，结束进程以释放 GPU"
    for p in $port_pids; do
      kill "$p" 2>/dev/null || true
    done
    sleep 2
    for p in $port_pids; do
      kill -9 "$p" 2>/dev/null || true
    done
  elif command -v fuser &>/dev/null; then
    if fuser "$PORT/tcp" &>/dev/null; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] 发现端口 $PORT 被占用，使用 fuser 结束进程以释放 GPU"
      fuser -k "$PORT/tcp" 2>/dev/null || true
      sleep 2
    fi
  fi

  # 3) 结束本次由 run.sh 启动的 env_prepare.sh
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

  # 4) 检查 GPU 0 是否仍有本用户的残留进程（vLLM 子进程未完全退出）
  #    只处理属于 SELF_USER 的进程，跳过其他用户（避免误杀他人 GPU 任务）
  sleep 3   # 给进程组一点时间自然退出
  local gpu_pids
  gpu_pids=$(gpu0_pids)
  if [[ -n "$gpu_pids" ]]; then
    for pid in $gpu_pids; do
      local owner
      owner=$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')
      [[ -z "$owner" ]] && continue
      if [[ "$owner" == "$SELF_USER" ]]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU 0 残留本用户进程 (PID=$pid)，kill ..."
        kill "$pid" 2>/dev/null || true
        sleep 2
        kill -9 "$pid" 2>/dev/null || true
      else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU 0 上发现其他用户进程 ($owner, PID=$pid)，跳过"
      fi
    done
    sleep 3
    # 最终确认
    gpu_pids=$(gpu0_pids)
    if [[ -z "$gpu_pids" ]]; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU 0 显存已释放"
    else
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU 0 仍有进程占用 (PID: $gpu_pids)，可能为其他用户，不再干预"
    fi
  else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU 0 显存已释放"
  fi
}

echo "========== run.sh 开始 =========="
while true; do
  ensure_llm
  llm_rc=$?
  if [[ "$llm_rc" -eq 2 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] GPU 长期被他人占用，放弃当天任务，退出"
    exit 1
  fi
  if run_pipeline; then
    stop_llm_and_env_prepare
    clear_downloaded_pdfs
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] pipeline 执行成功，已关闭 LLM、清理 PDF，退出"
    exit 0
  fi
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] pipeline 未完全成功，${RETRY_INTERVAL_SEC}s 后重试"
  sleep "$RETRY_INTERVAL_SEC"
done
