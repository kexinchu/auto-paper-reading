"""
End-to-end pipeline: fetch -> stage1 (batched, parallel) -> filter -> stage2 -> HTML email.
Idempotent, config-driven, per-paper error handling with status in DB.

Pipeline phases:
  1. Fetch papers from arXiv + Semantic Scholar (Google Scholar removed)
  2. Cross-source dedup (ID + normalized title); filter already-done papers via DB
  3. Keyword pre-filter: skip Stage-1 LLM for papers with no topic keyword in abstract
  4. Batched + parallel Stage-1 classification; resume from DB checkpoint if available
  5. Sequential Stage-2 summarization (abstract-only fast path for high-relevance papers)
  6. Single topic-grouped HTML digest email (recovers any STAGE2_OK from prior failed runs)
  7. Log run statistics
"""

import json
import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from . import arxiv_client, blog_client, db, emailer, model_client, pdf_utils
from .config import load_config
from .topics import load_topics

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Title normalisation for cross-source deduplication
# ──────────────────────────────────────────────────────────────────────────────

def _normalize_title(title: str) -> str:
    """Lowercase, strip accents, remove punctuation, collapse whitespace."""
    t = unicodedata.normalize("NFKD", title.lower())
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _save_failure_raw(
    db_path: Path, stage: str, arxiv_id: str, raw: str, error_msg: str, attempt: int
) -> Path:
    """Persist raw LLM output on parse failure for debugging. Returns path to .raw file."""
    try:
        logs_dir = db_path.resolve().parent.parent / "logs" / f"{stage}_failures"
        logs_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^\w\-.]", "_", arxiv_id)
        raw_path = logs_dir / f"{safe_id}.raw.txt"
        meta_path = logs_dir / f"{safe_id}.meta.txt"
        raw_path.write_text(raw or "(empty)", encoding="utf-8")
        meta_path.write_text(
            f"paper_id={arxiv_id}\nerror={error_msg}\nattempt={attempt}\n",
            encoding="utf-8",
        )
        logger.info("Saved failure raw for %s to %s (attempt %d)", arxiv_id, raw_path, attempt)
        return raw_path
    except OSError as e:
        logger.warning("Could not save failure raw: %s", e)
        return Path()


def _log_stage1_scores(
    db_path: Path,
    stage1_results: dict[str, dict[str, Any]],
    threshold: float,
) -> None:
    """Append Stage1 scores to logs/stage1_scores.log (JSONL) for threshold tuning."""
    if not stage1_results:
        return
    try:
        logs_dir = db_path.resolve().parent.parent / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_file = logs_dir / "stage1_scores.log"
        with open(log_file, "a", encoding="utf-8") as f:
            for arxiv_id, stage1 in stage1_results.items():
                topics = stage1.get("topics") or []
                max_rel = max((t.get("relevance", 0) for t in topics), default=0)
                rec = {
                    "paper_id": arxiv_id,
                    "max_relevance": round(max_rel, 4),
                    "decision": stage1.get("decision", "drop"),
                    "above_threshold": max_rel >= threshold,
                    "topics": [
                        {"topic_id": t.get("topic_id"), "relevance": round(t.get("relevance", 0), 4)}
                        for t in topics
                    ],
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        logger.info("Stage1 scores written to %s (%d papers)", log_file, len(stage1_results))
    except OSError as e:
        logger.warning("Could not write stage1_scores.log: %s", e)


# ──────────────────────────────────────────────────────────────────────────────
# Keyword pre-filter
# ──────────────────────────────────────────────────────────────────────────────

def _build_keyword_set(topics_config: list[dict]) -> frozenset[str]:
    """Collect all topic keywords, lower-cased, into a single set."""
    kws: set[str] = set()
    for topic in topics_config:
        for kw in topic.get("keywords", []):
            kws.add(kw.lower())
    return frozenset(kws)


def _has_keyword_match(paper: dict[str, Any], keyword_set: frozenset[str]) -> bool:
    """Return True if title + abstract contain at least one topic keyword."""
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    return any(kw in text for kw in keyword_set)


# ──────────────────────────────────────────────────────────────────────────────
# PDF download + text extraction helper
# ──────────────────────────────────────────────────────────────────────────────

def _get_full_text(
    paper: dict[str, Any],
    pdf_dir: Path,
    save_text: bool,
    text_dir: Path,
    db_path: Path,
) -> str | None:
    """
    Download PDF, extract text, then DELETE the PDF to free disk space.
    Falls back to abstract on any failure.
    Returns None if no usable text is available.
    """
    arxiv_id = paper["arxiv_id"]

    if not paper.get("pdf_url"):
        full_text = (paper.get("abstract") or "").strip() or "(No abstract)"
        if len(full_text) < 50:
            logger.warning("No PDF and abstract too short for %s", arxiv_id)
            db.mark_status(db_path, arxiv_id, db.FAILED, error_message="No PDF and abstract too short")
            return None
        db.mark_status(db_path, arxiv_id, db.TEXT_EXTRACTED)
        return full_text

    pdf_path = pdf_dir / f"{arxiv_id}.pdf"
    try:
        pdf_utils.download_pdf(paper["pdf_url"], pdf_path, timeout_s=90)
    except Exception as e:
        logger.warning("PDF download failed for %s (%s); falling back to abstract", arxiv_id, e)
        full_text = (paper.get("abstract") or "").strip() or "(No abstract)"
        if len(full_text) < 50:
            db.mark_status(db_path, arxiv_id, db.FAILED, error_message="PDF failed and abstract too short")
            return None
        db.mark_status(db_path, arxiv_id, db.TEXT_EXTRACTED)
        return full_text

    db.mark_status(db_path, arxiv_id, db.PDF_DOWNLOADED)

    try:
        full_text = pdf_utils.extract_text(pdf_path)
    except Exception as e:
        logger.warning("Text extraction failed for %s (%s); falling back to abstract", arxiv_id, e)
        full_text = (paper.get("abstract") or "").strip() or "(No abstract)"
        if len(full_text) < 50:
            db.mark_status(db_path, arxiv_id, db.FAILED, error_message=f"PDF extraction failed: {e}")
            return None
        db.mark_status(db_path, arxiv_id, db.TEXT_EXTRACTED)
        return full_text
    finally:
        # Always delete PDF after extraction to free disk space
        try:
            if pdf_path.exists():
                pdf_path.unlink()
        except Exception as e:
            logger.debug("Could not delete PDF %s: %s", pdf_path, e)

    if save_text:
        (text_dir / f"{arxiv_id}.txt").write_text(full_text, encoding="utf-8")

    n_chars = len(full_text.strip())
    if full_text.strip().startswith("[Extraction failed:") or n_chars < 100:
        fallback = (paper.get("abstract") or "").strip() or "(No abstract)"
        if len(fallback) >= 50:
            logger.warning("PDF text ineffective for %s (%d chars); using abstract", arxiv_id, n_chars)
            db.mark_status(db_path, arxiv_id, db.TEXT_EXTRACTED)
            return fallback
        db.mark_status(db_path, arxiv_id, db.FAILED, error_message=f"PDF text too short ({n_chars} chars)")
        return None

    db.mark_status(db_path, arxiv_id, db.TEXT_EXTRACTED)
    return full_text


# ──────────────────────────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────────────────────────

def run_pipeline(config_path: str | Path, topics_path: str | Path) -> dict[str, int]:
    """
    Load config and topics, ensure DB/storage dirs, fetch papers, then process.
    Returns a stats dict with counts for the run.
    """
    run_start = datetime.now(timezone.utc)
    config = load_config(config_path)
    topics_list = load_topics(topics_path)

    storage = config["storage"]
    db_path = Path(storage["db_path"])
    pdf_dir = Path(storage["pdf_dir"])
    text_dir = Path(storage["text_dir"])
    save_text = storage["save_text"]
    pdf_dir.mkdir(parents=True, exist_ok=True)
    if save_text:
        text_dir.mkdir(parents=True, exist_ok=True)
    db.ensure_db(db_path)

    model_cfg = config["model"]
    client = OpenAI(
        base_url=model_cfg["base_url"],
        api_key=model_cfg.get("api_key") or "dummy",
        timeout=model_cfg.get("timeout_s", 60),
    )
    model_name = model_cfg["model_name"]
    stage1_model_name = model_cfg.get("stage1_model_name") or model_name
    stage1_workers = int(model_cfg.get("stage1_workers", 1))
    # Batch multiple papers into one Stage-1 LLM call (reduces API call count)
    stage1_batch_size = int(model_cfg.get("stage1_batch_size", 1))
    temperature = model_cfg.get("temperature", 0)
    timeout_s = model_cfg.get("timeout_s", 120)
    # vLLM 在启用 --reasoning-parser 时会把 thinking 放在 message.reasoning、最终答案放在 message.content；我们只用 content 解析
    # 仅当显式关闭 thinking 时才传 extra_body（默认不传，保留推理）
    enable_thinking = model_cfg.get("enable_thinking", True)
    llm_extra_body = None if enable_thinking else {"chat_template_kwargs": {"enable_thinking": False}}
    stage1_max_tokens = int(model_cfg.get("stage1_max_tokens", 8192))
    stage2_max_tokens = int(model_cfg.get("stage2_max_tokens", 8192))

    threshold_cfg = config["thresholds"]
    threshold = threshold_cfg["relevance"]
    # Abstract-only fast path: skip PDF when abstract is rich + relevance is very high
    abstract_only_threshold = float(threshold_cfg.get("abstract_only_relevance", 0.92))
    abstract_min_length = int(threshold_cfg.get("abstract_min_length", 500))

    keyword_set = _build_keyword_set(topics_list)
    logger.debug("Keyword pre-filter: %d unique keywords across %d topics",
                 len(keyword_set), len(topics_list))

    # ── Fetch papers ──────────────────────────────────────────────────────────
    arxiv_cfg = config["arxiv"]
    papers = list(arxiv_client.fetch_papers(
        categories=arxiv_cfg["categories"],
        max_results_per_category=arxiv_cfg["max_results_per_category"],
        days_back=arxiv_cfg.get("days_back", 1),
    ))
    seen_ids: set[str] = {p["arxiv_id"] for p in papers}
    seen_titles: set[str] = {_normalize_title(p["title"]) for p in papers}
    # Seed seen_titles with already-processed papers from DB to avoid cross-day, cross-source dups
    # (e.g. paper emailed yesterday via arXiv ID, returns today via Semantic Scholar with a different ID)
    for t in db.get_processed_titles(db_path):
        seen_titles.add(_normalize_title(t))

    # Semantic Scholar API (no browser, no captcha)
    ss_cfg = config.get("semantic_scholar") or {}
    if ss_cfg.get("enabled") and ss_cfg.get("queries"):
        try:
            from . import semantic_scholar_client
            ss_papers = semantic_scholar_client.fetch_papers(
                queries=ss_cfg["queries"],
                limit=ss_cfg.get("limit", 10),
                top_k_by_relevance=ss_cfg.get("top_k_by_relevance"),
                delay_between_queries=ss_cfg.get("delay_between_queries", 8.0),
                max_retries_429=ss_cfg.get("max_retries_429", 3),
                api_key=ss_cfg.get("api_key"),
                user_agent=ss_cfg.get("user_agent"),
            )
            added = 0
            for p in ss_papers:
                norm = _normalize_title(p["title"])
                if p["arxiv_id"] not in seen_ids and norm not in seen_titles:
                    papers.append(p)
                    seen_ids.add(p["arxiv_id"])
                    seen_titles.add(norm)
                    added += 1
            logger.info("Semantic Scholar: added %d unique papers", added)
        except Exception as e:
            logger.warning("Semantic Scholar fetch failed: %s", e)

    total_fetched = len(papers)
    logger.info("Fetched %d papers total (after cross-source dedup)", total_fetched)

    stats: dict[str, int] = {
        "total": total_fetched,
        "skipped_existing": 0,
        "skipped_keyword": 0,
        "stage1_run": 0,
        "stage1_failed": 0,
        "skipped_irrelevant": 0,
        "relevant": 0,
        "abstract_only": 0,
        "stage2_ok": 0,
        "stage2_failed": 0,
        "emailed": 0,
    }

    # ── Phase 1: Filter already-done + keyword pre-filter ─────────────────────
    new_papers: list[dict[str, Any]] = []
    for paper in papers:
        arxiv_id = paper["arxiv_id"]

        if db.is_in_progress_or_processed(db_path, arxiv_id):
            stats["skipped_existing"] += 1
            continue

        if not _has_keyword_match(paper, keyword_set):
            db.upsert_paper_metadata(
                db_path, arxiv_id, paper["title"],
                ",".join(paper.get("categories", [])), status=db.NEW,
            )
            db.mark_status(db_path, arxiv_id, db.SKIPPED)
            stats["skipped_keyword"] += 1
            continue

        db.upsert_paper_metadata(
            db_path, arxiv_id, paper["title"],
            ",".join(paper.get("categories", [])), status=db.NEW,
        )
        new_papers.append(paper)

    logger.info(
        "%d new papers for Stage 1 (keyword pre-filter: %d skipped)",
        len(new_papers), stats["skipped_keyword"],
    )
    stats["stage1_run"] = len(new_papers)

    # ── Phase 2: Batched + parallel Stage-1 classification ───────────────────
    stage1_restart_wait = 30 if stage1_workers > 1 else model_client.SERVER_RESTART_WAIT_S
    stage1_results: dict[str, dict] = {}

    def _run_stage1_single(paper: dict[str, Any]) -> tuple[str, dict | None]:
        """Classify a single paper; checkpoint-resumes from DB. Retries up to 3 times on parse failure."""
        arxiv_id = paper["arxiv_id"]
        try:
            existing = db.get_paper(db_path, arxiv_id)
            if existing and existing.get("stage1_json") and existing["status"] in (
                db.STAGE1_OK, db.STAGE1_RELEVANT, db.PDF_DOWNLOADED, db.TEXT_EXTRACTED,
            ):
                stage1 = json.loads(existing["stage1_json"])
                logger.debug("Stage1 checkpoint recovered: %s", arxiv_id)
                return arxiv_id, stage1

            messages = model_client.build_stage1_prompt(topics_list, paper)
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    if attempt == 0:
                        raw = model_client.chat_completion(
                            client, stage1_model_name, messages,
                            temperature=temperature, max_tokens=stage1_max_tokens, timeout_s=timeout_s,
                            server_restart_wait_s=stage1_restart_wait,
                            extra_body=llm_extra_body,
                        )
                    elif attempt == 1:
                        # Repair: ask model to fix previous invalid output
                        repair = [{"role": "user", "content":
                                   "Return only valid JSON, no markdown, no thinking. Previous reply had errors.\n\n"
                                   + (raw[:8000] if raw else "")}]
                        raw = model_client.chat_completion(
                            client, stage1_model_name, repair,
                            temperature=0, max_tokens=stage1_max_tokens, timeout_s=timeout_s,
                            server_restart_wait_s=stage1_restart_wait,
                            extra_body=llm_extra_body,
                        )
                    else:
                        # Retry from scratch with original prompt
                        raw = model_client.chat_completion(
                            client, stage1_model_name, messages,
                            temperature=0, max_tokens=stage1_max_tokens, timeout_s=timeout_s,
                            server_restart_wait_s=stage1_restart_wait,
                            extra_body=llm_extra_body,
                        )
                    stage1 = model_client.parse_stage1_json(raw, arxiv_id)
                    db.mark_status(db_path, arxiv_id, db.STAGE1_OK,
                                   stage1_json=json.dumps(stage1, ensure_ascii=False))
                    return arxiv_id, stage1
                except ValueError as e:
                    last_error = e
                    _save_failure_raw(db_path, "stage1", arxiv_id, raw, str(e), attempt + 1)
                    # Programmatic repair before another LLM call
                    stage1, _ = model_client.try_parse_stage1_aggressive(raw, arxiv_id)
                    if stage1 is not None:
                        logger.info("Stage1 recovered for %s via aggressive parse (attempt %d)", arxiv_id, attempt + 1)
                        db.mark_status(db_path, arxiv_id, db.STAGE1_OK,
                                       stage1_json=json.dumps(stage1, ensure_ascii=False))
                        return arxiv_id, stage1
                    if attempt < 2:
                        logger.info("Stage1 parse failed for %s (attempt %d/3), retrying LLM: %s", arxiv_id, attempt + 1, e)
                    continue
            assert last_error is not None
            raise last_error
        except Exception as e:
            logger.warning("Stage1 failed for %s after retries: %s", arxiv_id, e)
            db.mark_status(db_path, arxiv_id, db.FAILED, error_message=str(e))
            return arxiv_id, None

    def _run_stage1_batch(batch: list[dict[str, Any]]) -> list[tuple[str, dict | None]]:
        """
        Classify a batch of papers in a single LLM call.
        Falls back to individual calls if batch parsing fails or some papers are unmatched.
        """
        # Separate checkpoint-recoverable papers from those needing LLM
        results: list[tuple[str, dict | None]] = []
        need_llm: list[dict[str, Any]] = []

        for paper in batch:
            arxiv_id = paper["arxiv_id"]
            existing = db.get_paper(db_path, arxiv_id)
            if existing and existing.get("stage1_json") and existing["status"] in (
                db.STAGE1_OK, db.STAGE1_RELEVANT, db.PDF_DOWNLOADED, db.TEXT_EXTRACTED,
            ):
                stage1 = json.loads(existing["stage1_json"])
                logger.debug("Stage1 checkpoint recovered: %s", arxiv_id)
                results.append((arxiv_id, stage1))
            else:
                need_llm.append(paper)

        if not need_llm:
            return results

        # 单篇模式（stage1_batch_size <= 1）：不做 batch 请求，逐篇调用以减轻 GPU 压力
        if stage1_batch_size <= 1:
            for paper in need_llm:
                results.append(_run_stage1_single(paper))
            return results

        # Try batch LLM call for papers needing classification
        try:
            messages = model_client.build_stage1_batch_prompt(topics_list, need_llm)
            # Batch: per-paper room, cap to avoid OOM (e.g. 8192 * batch_size capped at 32k)
            batch_max = min(stage1_max_tokens * len(need_llm), 32768)
            raw = model_client.chat_completion(
                client, stage1_model_name, messages,
                temperature=temperature, max_tokens=batch_max,
                timeout_s=timeout_s * 2,  # batches need more time
                server_restart_wait_s=stage1_restart_wait,
                extra_body=llm_extra_body,
            )
            batch_results = model_client.parse_stage1_batch_json(raw, need_llm)
            matched_ids = {aid for aid, _ in batch_results}

            # Save results to DB
            for arxiv_id, stage1 in batch_results:
                if stage1 is not None:
                    db.mark_status(db_path, arxiv_id, db.STAGE1_OK,
                                   stage1_json=json.dumps(stage1, ensure_ascii=False))
                    results.append((arxiv_id, stage1))
                else:
                    results.append((arxiv_id, None))

            # Fall back to individual calls for unmatched papers
            unmatched = [p for p in need_llm if p["arxiv_id"] not in matched_ids]
            if unmatched:
                logger.warning(
                    "Batch Stage1: %d/%d unmatched; falling back individually",
                    len(unmatched), len(need_llm),
                )
                for paper in unmatched:
                    results.append(_run_stage1_single(paper))

        except Exception as e:
            logger.warning(
                "Batch Stage1 failed (%s); falling back to %d individual calls",
                e, len(need_llm),
            )
            for paper in need_llm:
                results.append(_run_stage1_single(paper))

        return results

    # Group into batches
    batches = [
        new_papers[i : i + stage1_batch_size]
        for i in range(0, len(new_papers), stage1_batch_size)
    ]
    if stage1_batch_size <= 1:
        logger.info("Stage 1: %d papers, single-paper mode (no batching), workers=%d", len(new_papers), stage1_workers)
    else:
        logger.info(
            "Stage 1: %d papers in %d batches of %d (workers=%d)",
            len(new_papers), len(batches), stage1_batch_size, stage1_workers,
        )

    completed_count = 0

    def _run_batch_with_logging(batch: list[dict[str, Any]]) -> list[tuple[str, dict | None]]:
        results = _run_stage1_batch(batch)
        nonlocal completed_count
        completed_count += len(batch)
        logger.info(
            "Stage1 progress: %d/%d papers classified",
            completed_count, len(new_papers),
        )
        return results

    if stage1_workers > 1 and len(batches) > 1:
        with ThreadPoolExecutor(max_workers=stage1_workers) as executor:
            futures = [executor.submit(_run_batch_with_logging, b) for b in batches]
            for future in as_completed(futures):
                for arxiv_id, result in future.result():
                    if result is not None:
                        stage1_results[arxiv_id] = result
                    else:
                        stats["stage1_failed"] += 1
    else:
        for batch in batches:
            for arxiv_id, result in _run_batch_with_logging(batch):
                if result is not None:
                    stage1_results[arxiv_id] = result
                else:
                    stats["stage1_failed"] += 1

    logger.info(
        "Stage 1 complete: %d classified, %d failed",
        len(stage1_results), stats["stage1_failed"],
    )

    # Record Stage1 scores for threshold tuning (e.g. after model change)
    _log_stage1_scores(db_path, stage1_results, threshold)

    # ── Phase 3: Stage-2 for relevant papers ─────────────────────────────────
    digest_summaries: list[dict[str, Any]] = []

    for paper in new_papers:
        arxiv_id = paper["arxiv_id"]
        stage1 = stage1_results.get(arxiv_id)
        if stage1 is None:
            continue

        max_relevance = max(
            (t.get("relevance", 0) for t in stage1.get("topics", [])),
            default=0,
        )
        if max_relevance < threshold:
            db.mark_status(db_path, arxiv_id, db.SKIPPED)
            stats["skipped_irrelevant"] += 1
            continue

        stats["relevant"] += 1
        db.mark_status(db_path, arxiv_id, db.STAGE1_RELEVANT)

        try:
            # Abstract-only fast path: skip PDF when abstract is rich + relevance is very high
            abstract = (paper.get("abstract") or "").strip()
            if max_relevance >= abstract_only_threshold and len(abstract) >= abstract_min_length:
                full_text = abstract
                db.mark_status(db_path, arxiv_id, db.TEXT_EXTRACTED)
                stats["abstract_only"] += 1
                logger.debug(
                    "Abstract-only fast path for %s (relevance=%.2f, abstract=%d chars)",
                    arxiv_id, max_relevance, len(abstract),
                )
            else:
                full_text = _get_full_text(paper, pdf_dir, save_text, text_dir, db_path)
                if full_text is None:
                    stats["stage2_failed"] += 1
                    continue

            # Stage 2: up to 3 attempts (original -> repair -> retry from scratch)
            messages_s2 = model_client.build_stage2_prompt(
                paper, full_text, stage1.get("topics", []),
            )
            last_s2_error: Exception | None = None
            raw_s2 = ""
            for attempt in range(3):
                try:
                    if attempt == 0:
                        raw_s2 = model_client.chat_completion(
                            client, model_name, messages_s2,
                            temperature=temperature, max_tokens=stage2_max_tokens, timeout_s=timeout_s,
                            extra_body=llm_extra_body,
                        )
                    elif attempt == 1:
                        repair_msg = [{"role": "user", "content":
                                       "Return only valid JSON, no markdown, no thinking. Previous reply had errors.\n\n"
                                       + raw_s2[:12000]}]
                        raw_s2 = model_client.chat_completion(
                            client, model_name, repair_msg,
                            temperature=0, max_tokens=stage2_max_tokens, timeout_s=timeout_s,
                            extra_body=llm_extra_body,
                        )
                    else:
                        raw_s2 = model_client.chat_completion(
                            client, model_name, messages_s2,
                            temperature=0, max_tokens=stage2_max_tokens, timeout_s=timeout_s,
                            extra_body=llm_extra_body,
                        )
                    stage2 = model_client.parse_stage2_json(raw_s2, arxiv_id)
                    db.mark_status(
                        db_path, arxiv_id, db.STAGE2_OK,
                        stage2_json=json.dumps(stage2, ensure_ascii=False),
                    )
                    digest_summaries.append(stage2)
                    stats["stage2_ok"] += 1
                    logger.info("Stage2 done: %s", arxiv_id)
                    break
                except ValueError as e:
                    last_s2_error = e
                    _save_failure_raw(db_path, "stage2", arxiv_id, raw_s2, str(e), attempt + 1)
                    stage2, _ = model_client.try_parse_stage2_aggressive(raw_s2, arxiv_id)
                    if stage2 is not None:
                        logger.info("Stage2 recovered for %s via aggressive parse (attempt %d)", arxiv_id, attempt + 1)
                        db.mark_status(
                            db_path, arxiv_id, db.STAGE2_OK,
                            stage2_json=json.dumps(stage2, ensure_ascii=False),
                        )
                        digest_summaries.append(stage2)
                        stats["stage2_ok"] += 1
                        logger.info("Stage2 done: %s", arxiv_id)
                        break
                    if attempt < 2:
                        logger.info("Stage2 parse failed for %s (attempt %d/3), retrying LLM: %s", arxiv_id, attempt + 1, e)
                if attempt == 2:
                    raise (last_s2_error or RuntimeError("Stage2 parse failed"))

        except Exception as e:
            logger.exception("Stage2 error for %s: %s", arxiv_id, e)
            db.mark_status(db_path, arxiv_id, db.FAILED, error_message=str(e))
            stats["stage2_failed"] += 1

    # ── Phase 3b: Fetch blog posts (no LLM, direct to digest) ─────────────────
    blog_posts_for_digest: list[dict[str, Any]] = []
    blogs_cfg = config.get("blogs") or {}
    if blogs_cfg.get("enabled") and blogs_cfg.get("sources"):
        try:
            blog_days_back = int(blogs_cfg.get("days_back", 3))
            delay = float(blogs_cfg.get("delay_between_sources", 2.0))
            all_blog_posts = blog_client.fetch_all_blogs(
                blogs_cfg["sources"],
                days_back=blog_days_back,
                delay_between_sources=delay,
            )
            new_blog_count = 0
            for post in all_blog_posts:
                if db.is_blog_post_seen(db_path, post["url"]):
                    continue
                db.upsert_blog_post(
                    db_path, post["id"], post["title"], post["url"],
                    post["summary"], post["published"], post["source"],
                )
                blog_posts_for_digest.append(post)
                new_blog_count += 1
            # Also recover unemailed blog posts from prior failed runs
            for post in db.get_unemailed_blog_posts(db_path):
                if post["url"] not in {p["url"] for p in blog_posts_for_digest}:
                    blog_posts_for_digest.append(dict(post))
            logger.info(
                "Blogs: %d fetched, %d new, %d total for digest",
                len(all_blog_posts), new_blog_count, len(blog_posts_for_digest),
            )
        except Exception as e:
            logger.warning("Blog fetch failed: %s", e)

    # ── Phase 4: Recover any STAGE2_OK papers from prior failed email runs ────
    already_ids = {s.get("paper_id") for s in digest_summaries}
    for summary in db.get_unemailed_summaries(db_path):
        pid = summary.get("paper_id")
        if pid and pid not in already_ids:
            digest_summaries.append(summary)
            already_ids.add(pid)
            logger.info("Recovered STAGE2_OK paper for digest: %s", pid)

    # ── Phase 5: Topic-grouped HTML digest email(s); at most N papers per email ──
    has_papers = bool(digest_summaries)
    has_blogs = bool(blog_posts_for_digest)
    if has_papers or has_blogs:
        email_cfg = config["email"]
        max_per_email = int(email_cfg.get("max_papers_per_digest", 10))
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        total = len(digest_summaries)
        chunks: list[list[dict[str, Any]]] = [
            digest_summaries[i : i + max_per_email]
            for i in range(0, total, max_per_email)
        ] if digest_summaries else [[]]
        num_emails = len(chunks)
        for idx, chunk in enumerate(chunks):
            n = len(chunk)
            # Build subject line reflecting both papers and blogs
            parts = []
            if n:
                parts.append(f"{n} 篇论文")
            # Only include blog count in the first (or only) email chunk
            if blog_posts_for_digest and idx == 0:
                parts.append(f"{len(blog_posts_for_digest)} 篇博客")
            content_desc = " + ".join(parts) if parts else "digest"
            if num_emails > 1:
                subject = f"[AI Digest] {date_str} — {content_desc} (第 {idx + 1}/{num_emails} 封)"
            else:
                subject = f"[AI Digest] {date_str} — {content_desc}"
            # Only pass blog posts to first chunk to avoid duplication
            chunk_blogs = blog_posts_for_digest if idx == 0 else None
            html_body = emailer.format_html_digest(
                chunk, date_str, stats,
                topics_config=topics_list,
                blog_posts=chunk_blogs,
            )
            try:
                emailer.send_digest_email(
                    smtp_host=email_cfg["smtp_host"],
                    smtp_port=email_cfg["smtp_port"],
                    smtp_user=email_cfg.get("smtp_user", ""),
                    smtp_password=email_cfg.get("smtp_password", ""),
                    from_addr=email_cfg["from_addr"],
                    to_addr=email_cfg["to_addr"],
                    use_tls=email_cfg["use_tls"],
                    subject=subject,
                    body=html_body,
                    is_html=True,
                )
                for summary in chunk:
                    db.mark_status(db_path, summary["paper_id"], db.EMAILED)
                # Mark blog posts as emailed
                if chunk_blogs:
                    for post in chunk_blogs:
                        db.mark_blog_status(db_path, post["id"], db.EMAILED)
                stats["emailed"] += n
                stats["blogs_emailed"] = stats.get("blogs_emailed", 0) + len(chunk_blogs or [])
                logger.info("Digest email sent: %d papers + %d blogs (part %d/%d) -> %s",
                            n, len(chunk_blogs or []), idx + 1, num_emails, email_cfg["to_addr"])
            except Exception as e:
                logger.exception("Digest email failed (chunk %d/%d): %s", idx + 1, num_emails, e)
    else:
        logger.info("No relevant papers or blogs found; no email sent")

    # ── Phase 6: Log run summary ───────────────────────────────────────────────
    elapsed = (datetime.now(timezone.utc) - run_start).total_seconds()
    logger.info(
        "Pipeline finished in %.0fs | fetched=%d skipped_existing=%d skipped_keyword=%d "
        "stage1_run=%d stage1_failed=%d relevant=%d abstract_only=%d "
        "stage2_ok=%d stage2_failed=%d emailed=%d blogs=%d",
        elapsed,
        stats["total"], stats["skipped_existing"], stats["skipped_keyword"],
        stats["stage1_run"], stats["stage1_failed"], stats["relevant"], stats["abstract_only"],
        stats["stage2_ok"], stats["stage2_failed"], stats["emailed"],
        stats.get("blogs_emailed", 0),
    )
    return stats
