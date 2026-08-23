# arXiv Digest

Production-quality service that summarizes new arXiv papers daily for user-selected categories, using a local small model (OpenAI-compatible API) and sending email reports.

## Features

- **Config-driven**: `config.yaml` (arXiv categories, model API, thresholds, storage, email)
- **Topic-based filtering**: `topics.yaml` defines topics; Stage-1 classifies each paper and scores relevance
- **Two-stage pipeline**: Stage-1 (abstract → classification + relevance); Stage-2 (full text → structured summary) only for papers above relevance threshold
- **Focus topics**: ANNS / memory systems / Agent OS only; other papers are dropped before the digest
- **Topic briefing email**: Stage-3 clusters related topics into a few research threads and sends **one** Chinese digest (with a 今日判断 / thinking section), instead of one card or one email per paper
- **Idea exploration**: Stage-4 proposes ideas from the batch, checks related papers (in-batch + Semantic Scholar), screens potential and scope, and reports **all** explored ideas (pursue / watch / drop) in the same email
- **Idempotent**: SQLite stores per-paper status; reruns skip processed/in-progress papers
- **E2E tests**: `tests/test_e2e_pipeline.py` runs the full pipeline with mocked fetch/LLM/SMTP (use project `venv`)
- **Robust**: Retries with exponential backoff for arXiv, model API, and PDF download; per-paper errors don’t abort the run
- **Structured logging**: Timestamps, counts, and context on failures

## Requirements

- Python 3.11+
- Dependencies: `requests`, `PyYAML`, `openai`, `arxiv`, `pymupdf`, `feedparser` (optional). See project root `requirements.txt`.

## Setup

1. **Prepare Env**:

```bash
bash env_prepare.sh

# 执行
python3 -m src --config config/config.yaml --topics config/topics.yaml
```

2, **统一入口脚本 + 周期执行命令**
```bash
bash run.sh

# 每天 8:00 执行 run.sh，日志写到项目下 logs/run.log
0 8 * * * cd /path/to/auto-paper-reading && bash run.sh >> /path/to/auto-paper-reading/logs/run.log 2>&1
```

`run.sh` 启动前会检查 `GPU_IDS`（默认 `0,1`，对应两卡张量并行）。若被其他用户占用，每 `GPU_POLL_SEC` 秒看一次，**空闲后再启动**，不会抢卡。已有实例在等待或执行时，后来的 cron 会因 `logs/run.lock` 直接退出。

### vLLM 推理模型（Qwen3 等）

vLLM 支持**区分 thinking 与最终输出**：响应中 `message.reasoning` 为思考过程，`message.content` 仅为最终答案。本 pipeline 只使用 `content` 做 JSON 解析。

请用 **`--reasoning-parser`** 启动 vLLM，例如 Qwen3.8：

```bash
vllm serve ./Models/Qwen3.8-27B --served-model-name Qwen3.8-27B --tensor-parallel-size 2 --max-model-len 16384
```

这样 API 返回的 `content` 仅为最终 JSON，不会被长 thinking 占满 token 导致截断。不在请求里关闭 thinking（`enable_thinking` 默认 true），推理质量保留。
