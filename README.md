# arXiv Digest

Production-quality service that summarizes new arXiv papers daily for user-selected categories, using a local small model (OpenAI-compatible API) and sending email reports.

## Features

- **Config-driven**: `config.yaml` (arXiv categories, model API, thresholds, storage, email)
- **Topic-based filtering**: `topics.yaml` defines topics; Stage-1 classifies each paper and scores relevance
- **Two-stage pipeline**: Stage-1 (abstract → classification + relevance); Stage-2 (full text → structured summary) only for papers above relevance threshold
- **Idempotent**: SQLite stores per-paper status; reruns skip processed/in-progress papers
- **Robust**: Retries with exponential backoff for arXiv, model API, and PDF download; per-paper errors don’t abort the run
- **Structured logging**: Timestamps, counts, and context on failures

## Requirements

- Python 3.11+
- Dependencies: `requests`, `PyYAML`, `openai`, `arxiv`, `pymupdf`, `feedparser` (optional). See project root `requirements.txt`.

## Setup

1. **Install dependencies** (from repo root):

   ```bash
   pip install -r requirements.txt
   ```

2. **Copy and edit config**:

   ```bash
   cp arxiv_digest/sample_config.yaml config.yaml
   cp arxiv_digest/sample_topics.yaml topics.yaml
   # Edit config.yaml: model base_url, api_key (or set OPENAI_API_KEY), email SMTP, storage paths
   # Edit topics.yaml: topic id, name, description, optional keywords
   ```

3. **Optional env overrides**:

   - `OPENAI_API_KEY`: overrides `model.api_key`
   - `ARXIV_DIGEST_SMTP_PASSWORD`: overrides `email.smtp_password`

4. **Local model**: Run your OpenAI-compatible API (e.g. vLLM with Qwen) so `model.base_url` (e.g. `http://127.0.0.1:8000/v1`) is reachable.

## Run

From the **project root** (where `config.yaml` and `topics.yaml` live):

```bash
# One-shot run
python -m arxiv_digest

# With custom paths
python -m arxiv_digest --config /path/to/config.yaml --topics /path/to/topics.yaml

# Verbose
python -m arxiv_digest -v
```

Or:

```bash
python -m arxiv_digest.cli
```

## Daily run (cron)

Example: run every day at 8:00 AM (adjust path and venv):

```bash
0 8 * * * cd /path/to/auto-paper-reading && . venv/bin/activate && python -m arxiv_digest >> logs/arxiv_digest.log 2>&1
```

Or use a systemd timer / your scheduler of choice.

## Config overview

| Section     | Key examples |
|------------|----------------|
| `arxiv`    | `categories`, `max_results_per_category`, `days_back` |
| `model`    | `base_url`, `api_key`, `model_name`, `temperature`, `timeout_s` |
| `thresholds` | `relevance` (e.g. 0.8) |
| `storage`  | `db_path`, `pdf_dir`, `text_dir`, `save_text` |
| `email`    | `smtp_host`, `smtp_port`, `from_addr`, `to_addr`, `use_tls` |

## Database

SQLite table `papers`: `arxiv_id`, `title`, `categories`, `status`, `created_at`, `updated_at`, `stage1_json`, `stage2_json`, `error_message`.  
Status flow: `NEW` → `STAGE1_OK` → `STAGE1_RELEVANT` → `PDF_DOWNLOADED` → `TEXT_EXTRACTED` → `STAGE2_OK` → `EMAILED`.  
Papers with status `EMAILED`, `SKIPPED`, or `STAGE2_OK` are not processed again.

## Tests

From repo root:

```bash
pytest arxiv_digest/tests -v
```

## Package layout

- `config.py` – load/validate YAML, env overrides  
- `topics.py` – topic schema from YAML  
- `arxiv_client.py` – fetch papers by category with date filter  
- `model_client.py` – OpenAI-compatible chat + Stage-1/2 prompts and JSON parsing  
- `pdf_utils.py` – PDF download and text extraction (PyMuPDF)  
- `db.py` – SQLite helpers and status  
- `pipeline.py` – end-to-end orchestration  
- `emailer.py` – SMTP digest email  
- `cli.py` – entry point  
