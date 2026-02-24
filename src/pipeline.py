"""
End-to-end pipeline: fetch -> stage1 -> filter -> download PDF -> extract text -> stage2 -> email.
Idempotent, config-driven, per-paper error handling with status in DB.
"""

import json
import logging
from pathlib import Path
from typing import Any

from openai import OpenAI

from . import arxiv_client, db, emailer, model_client, pdf_utils
from .config import load_config
from .topics import load_topics

logger = logging.getLogger(__name__)


def run_pipeline(config_path: str | Path, topics_path: str | Path) -> None:
    """
    Load config and topics, ensure DB/storage dirs, fetch papers, then process each.
    SQL 使用约定：
    1) 表不存在时：ensure_db(db_path) 创建 papers 表（CREATE TABLE IF NOT EXISTS）。
    2) 送 LLM 前：用 is_in_progress_or_processed(db_path, arxiv_id) 检查，已处理或进行中则跳过。
    3) 每步完成后：mark_status / upsert_paper_metadata 写入状态，用于后续去重与断点续跑。
    4) 测试清空表：可运行 tests/clear_papers_db.py 清空 papers 表数据。
    """
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
    temperature = model_cfg.get("temperature", 0)
    timeout_s = model_cfg.get("timeout_s", 120)
    threshold = config["thresholds"]["relevance"]

    arxiv_cfg = config["arxiv"]
    papers = arxiv_client.fetch_papers(
        categories=arxiv_cfg["categories"],
        max_results_per_category=arxiv_cfg["max_results_per_category"],
        days_back=arxiv_cfg.get("days_back", 1),
    )
    logger.info("Fetched %d papers; starting pipeline", len(papers))

    for paper in papers:
        arxiv_id = paper["arxiv_id"]
        title = paper["title"]
        categories_str = ",".join(paper.get("categories", []))

        if db.is_in_progress_or_processed(db_path, arxiv_id):
            logger.info("Skip %s (already processed or in progress)", arxiv_id)
            continue

        db.upsert_paper_metadata(db_path, arxiv_id, title, categories_str, status=db.NEW)

        try:
            # Stage 1
            messages_s1 = model_client.build_stage1_prompt(topics_list, paper)
            raw_s1 = model_client.chat_completion(
                client, model_name, messages_s1,
                temperature=temperature, max_tokens=2048, timeout_s=timeout_s,
            )
            try:
                stage1 = model_client.parse_stage1_json(raw_s1, arxiv_id)
            except ValueError as e:
                logger.warning(
                    "Stage1 JSON parse failed for %s, retry with repair: %s | raw_s1[:500]=%r",
                    arxiv_id, e, (raw_s1 or "")[:500],
                )
                repair_msg = [{"role": "user", "content": "Return only valid JSON, no markdown or explanation. Your previous reply had errors.\n\n" + raw_s1[:8000]}]
                try:
                    raw_s1 = model_client.chat_completion(client, model_name, repair_msg, temperature=0, max_tokens=2048, timeout_s=timeout_s)
                    stage1 = model_client.parse_stage1_json(raw_s1, arxiv_id)
                    logger.info(f"Stage1 JSON repair successful for {arxiv_id}: {raw_s1}")
                except (ValueError, Exception) as e2:
                    logger.warning("Stage1 JSON repair failed for %s: %s", arxiv_id, e2)
                    db.mark_status(db_path, arxiv_id, db.FAILED, error_message=str(e2))
                    continue

            db.mark_status(
                db_path, arxiv_id, db.STAGE1_OK,
                stage1_json=json.dumps(stage1, ensure_ascii=False),
            )

            max_relevance = max(
                (t.get("relevance", 0) for t in stage1.get("topics", [])),
                default=0,
            )
            # if max_relevance < threshold:
            #     db.mark_status(db_path, arxiv_id, db.SKIPPED)
            #     logger.info("Skip %s (relevance %.2f < %.2f)", arxiv_id, max_relevance, threshold)
            #     continue

            db.mark_status(db_path, arxiv_id, db.STAGE1_RELEVANT)

            # Download PDF
            pdf_path = pdf_dir / f"{arxiv_id}.pdf"
            try:
                pdf_utils.download_pdf(paper["pdf_url"], pdf_path, timeout_s=90)
            except Exception as e:
                logger.exception("PDF download failed for %s: %s", arxiv_id, e)
                db.mark_status(db_path, arxiv_id, db.FAILED, error_message=f"PDF: {e}")
                continue
            db.mark_status(db_path, arxiv_id, db.PDF_DOWNLOADED)

            # Extract text
            try:
                full_text = pdf_utils.extract_text(pdf_path, use_ocr=False)
            except Exception as e:
                logger.warning("Text extraction failed for %s: %s", arxiv_id, e)
                db.mark_status(db_path, arxiv_id, db.FAILED, error_message=f"PDF text extraction: {e}")
                continue
            if save_text:
                (text_dir / f"{arxiv_id}.txt").write_text(full_text, encoding="utf-8")
            n_chars = len(full_text.strip())
            if full_text.strip().startswith("[Extraction failed:") or n_chars < 100:
                logger.warning("PDF text extraction ineffective for %s (%d chars); skip Stage2", arxiv_id, n_chars)
                db.mark_status(db_path, arxiv_id, db.FAILED, error_message=f"PDF text too short or extraction failed ({n_chars} chars)")
                continue
            db.mark_status(db_path, arxiv_id, db.TEXT_EXTRACTED)

            # Stage 2
            messages_s2 = model_client.build_stage2_prompt(
                paper, full_text, stage1.get("topics", []),
            )
            raw_s2 = model_client.chat_completion(
                client, model_name, messages_s2,
                temperature=temperature, max_tokens=4096, timeout_s=timeout_s,
            )
            try:
                stage2 = model_client.parse_stage2_json(raw_s2, arxiv_id)
            except ValueError as e:
                logger.warning("Stage2 JSON parse failed for %s, retry with repair: %s", arxiv_id, e)
                repair_msg = [{"role": "user", "content": "Return only valid JSON, no markdown or explanation. Your previous reply had errors.\n\n" + raw_s2[:12000]}]
                try:
                    raw_s2 = model_client.chat_completion(client, model_name, repair_msg, temperature=0, max_tokens=4096, timeout_s=timeout_s)
                    stage2 = model_client.parse_stage2_json(raw_s2, arxiv_id)
                except (ValueError, Exception) as e2:
                    logger.warning("Stage2 JSON repair failed for %s: %s", arxiv_id, e2)
                    db.mark_status(db_path, arxiv_id, db.FAILED, error_message=f"Stage2 parse: {e2}")
                    continue

            db.mark_status(
                db_path, arxiv_id, db.STAGE2_OK,
                stage2_json=json.dumps(stage2, ensure_ascii=False),
            )

            # Email
            email_cfg = config["email"]
            subject = f"[arXiv Digest] {arxiv_id} {title[:80]}"
            body = emailer.format_email_body(stage2, pdf_path=pdf_path, include_json=True)
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
                    body=body,
                )
            except Exception as e:
                logger.exception("Email failed for %s: %s", arxiv_id, e)
                db.mark_status(db_path, arxiv_id, db.FAILED, error_message=f"Email: {e}")
                continue

            db.mark_status(db_path, arxiv_id, db.EMAILED)
            logger.info("Done: %s -> EMAILED", arxiv_id)

        except Exception as e:
            logger.exception("Pipeline error for %s: %s", arxiv_id, e)
            db.mark_status(db_path, arxiv_id, db.FAILED, error_message=str(e))

    logger.info("Pipeline run finished")
