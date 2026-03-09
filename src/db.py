"""
SQLite persistence for paper processing state. Idempotent and transaction-safe.
Uses WAL mode for concurrent write support.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Status enum values
NEW = "NEW"
SKIPPED = "SKIPPED"
STAGE1_OK = "STAGE1_OK"
STAGE1_RELEVANT = "STAGE1_RELEVANT"
PDF_DOWNLOADED = "PDF_DOWNLOADED"
TEXT_EXTRACTED = "TEXT_EXTRACTED"
STAGE2_OK = "STAGE2_OK"
EMAILED = "EMAILED"
FAILED = "FAILED"

# Max retry attempts for FAILED papers before permanently skipping
MAX_RETRY_COUNT = 3

# Consider "processed" (skip re-processing): already emailed, skipped, or stage2 done
PROCESSED_STATUSES = frozenset({EMAILED, SKIPPED, STAGE2_OK})
# In-flight: do not start again
IN_PROGRESS_STATUSES = frozenset(
    {NEW, STAGE1_OK, STAGE1_RELEVANT, PDF_DOWNLOADED, TEXT_EXTRACTED}
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ensure_db(db_path: str | Path) -> None:
    """Create DB file and papers table if they do not exist. Run migrations."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _conn(path) as conn:
        # Enable WAL mode for concurrent read/write access
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                arxiv_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                categories TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                stage1_json TEXT,
                stage2_json TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status)"
        )
        # Migration: add retry_count column if missing (for existing DBs)
        try:
            conn.execute("ALTER TABLE papers ADD COLUMN retry_count INTEGER DEFAULT 0")
            logger.info("Migration: added retry_count column")
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.commit()
    logger.info("Database ready at %s", path)


@contextmanager
def _conn(db_path: str | Path):
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def upsert_paper_metadata(
    db_path: str | Path,
    arxiv_id: str,
    title: str,
    categories: str,
    status: str = NEW,
) -> None:
    """Insert or update paper row. If row exists, update title/categories/updated_at only."""
    now = _utc_now()
    with _conn(db_path) as conn:
        cur = conn.execute(
            "SELECT status FROM papers WHERE arxiv_id = ?", (arxiv_id,)
        )
        row = cur.fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO papers (arxiv_id, title, categories, status, created_at, updated_at, retry_count)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (arxiv_id, title, categories, status, now, now),
            )
            logger.debug("Inserted paper %s status=%s", arxiv_id, status)
        else:
            conn.execute(
                """UPDATE papers SET title = ?, categories = ?, updated_at = ?
                   WHERE arxiv_id = ?""",
                (title, categories, now, arxiv_id),
            )
            logger.debug("Updated metadata for paper %s", arxiv_id)
        conn.commit()


def mark_status(
    db_path: str | Path,
    arxiv_id: str,
    status: str,
    stage1_json: str | None = None,
    stage2_json: str | None = None,
    error_message: str | None = None,
) -> None:
    """Set status and optional stage JSON / error. Uses transaction.
    When marking FAILED, increments retry_count automatically.
    """
    now = _utc_now()
    with _conn(db_path) as conn:
        if status == FAILED:
            conn.execute(
                """UPDATE papers SET status = ?, updated_at = ?,
                   stage1_json = COALESCE(?, stage1_json),
                   stage2_json = COALESCE(?, stage2_json),
                   error_message = COALESCE(?, error_message),
                   retry_count = retry_count + 1
                   WHERE arxiv_id = ?""",
                (status, now, stage1_json, stage2_json, error_message, arxiv_id),
            )
        else:
            conn.execute(
                """UPDATE papers SET status = ?, updated_at = ?,
                   stage1_json = COALESCE(?, stage1_json),
                   stage2_json = COALESCE(?, stage2_json),
                   error_message = COALESCE(?, error_message)
                   WHERE arxiv_id = ?""",
                (status, now, stage1_json, stage2_json, error_message, arxiv_id),
            )
        if conn.total_changes == 0:
            logger.warning("mark_status: no row updated for arxiv_id=%s", arxiv_id)
        conn.commit()
    logger.info("Paper %s -> %s", arxiv_id, status)


def get_status(db_path: str | Path, arxiv_id: str) -> str | None:
    """Return current status for arxiv_id, or None if not found."""
    with _conn(db_path) as conn:
        cur = conn.execute("SELECT status FROM papers WHERE arxiv_id = ?", (arxiv_id,))
        row = cur.fetchone()
    return row["status"] if row else None


def is_processed(db_path: str | Path, arxiv_id: str) -> bool:
    """True if paper should not be processed again (EMAILED, SKIPPED, or STAGE2_OK)."""
    s = get_status(db_path, arxiv_id)
    return s in PROCESSED_STATUSES


def is_in_progress_or_processed(db_path: str | Path, arxiv_id: str) -> bool:
    """True if we should skip this paper entirely.

    Only truly-done papers are skipped:
      - EMAILED / SKIPPED / STAGE2_OK  (PROCESSED_STATUSES)
      - FAILED with retry_count >= MAX_RETRY_COUNT

    Papers in mid-pipeline states (STAGE1_OK, STAGE1_RELEVANT, etc.) are NOT
    skipped so that interrupted runs can be resumed via checkpoint logic in the
    pipeline (Stage-1/Stage-2 results are recovered from DB if already present).
    """
    with _conn(db_path) as conn:
        cur = conn.execute(
            "SELECT status, retry_count FROM papers WHERE arxiv_id = ?", (arxiv_id,)
        )
        row = cur.fetchone()
    if row is None:
        return False
    status = row["status"]
    if status in PROCESSED_STATUSES:
        return True
    if status == FAILED:
        retry_count = row["retry_count"] or 0
        if retry_count >= MAX_RETRY_COUNT:
            logger.debug("Skip %s: FAILED retry_count=%d >= %d", arxiv_id, retry_count, MAX_RETRY_COUNT)
            return True
        return False  # Allow retry
    # NEW / STAGE1_OK / STAGE1_RELEVANT / PDF_DOWNLOADED / TEXT_EXTRACTED → resumable
    return False


def get_paper(db_path: str | Path, arxiv_id: str) -> dict[str, Any] | None:
    """Return full row as dict or None."""
    with _conn(db_path) as conn:
        cur = conn.execute("SELECT * FROM papers WHERE arxiv_id = ?", (arxiv_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return dict(row)


def get_unemailed_summaries(db_path: str | Path) -> list[dict[str, Any]]:
    """Return Stage-2 summaries for papers in STAGE2_OK state (finished but not yet emailed).

    This recovers papers whose Stage-2 succeeded but the digest email failed on a
    previous run, so they can be included in the next digest without re-running Stage 2.
    """
    import json as _json
    with _conn(db_path) as conn:
        cur = conn.execute(
            "SELECT arxiv_id, stage2_json FROM papers WHERE status = ? AND stage2_json IS NOT NULL",
            (STAGE2_OK,),
        )
        results = []
        for row in cur.fetchall():
            try:
                results.append(_json.loads(row["stage2_json"]))
            except Exception as e:
                logger.warning("Could not parse stage2_json for %s: %s", row["arxiv_id"], e)
        return results


def get_processed_titles(db_path: str | Path) -> set[str]:
    """Return titles of all papers not in FAILED status (to detect cross-source duplicates)."""
    with _conn(db_path) as conn:
        cur = conn.execute(
            "SELECT title FROM papers WHERE status != ?", (FAILED,)
        )
        return {row["title"] for row in cur.fetchall() if row["title"]}


def get_run_stats(db_path: str | Path, since: str | None = None) -> dict[str, int]:
    """Return counts grouped by status. Optionally filter by updated_at >= since."""
    with _conn(db_path) as conn:
        if since:
            cur = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM papers WHERE updated_at >= ? GROUP BY status",
                (since,),
            )
        else:
            cur = conn.execute("SELECT status, COUNT(*) as cnt FROM papers GROUP BY status")
        return {row["status"]: row["cnt"] for row in cur.fetchall()}
