"""
SQLite persistence for paper processing state. Idempotent and transaction-safe.
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

# Consider "processed" (skip re-processing): already emailed, skipped, or stage2 done
PROCESSED_STATUSES = frozenset({EMAILED, SKIPPED, STAGE2_OK})
# In-flight: do not start again
IN_PROGRESS_STATUSES = frozenset(
    {NEW, STAGE1_OK, STAGE1_RELEVANT, PDF_DOWNLOADED, TEXT_EXTRACTED}
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ensure_db(db_path: str | Path) -> None:
    """Create DB file and papers table if they do not exist."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _conn(path) as conn:
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
                error_message TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status)"
        )
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
    """Insert or update paper row. If row exists, update title/categories/updated_at only when status is NEW."""
    now = _utc_now()
    with _conn(db_path) as conn:
        cur = conn.execute(
            "SELECT status FROM papers WHERE arxiv_id = ?", (arxiv_id,)
        )
        row = cur.fetchone()
        if row is None:
            conn.execute(
                """INSERT INTO papers (arxiv_id, title, categories, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
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
    """Set status and optional stage JSON / error. Uses transaction."""
    now = _utc_now()
    with _conn(db_path) as conn:
        conn.execute(
            """UPDATE papers SET status = ?, updated_at = ?, stage1_json = COALESCE(?, stage1_json),
               stage2_json = COALESCE(?, stage2_json), error_message = COALESCE(?, error_message)
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
    """True if we should skip starting this paper (already processed or in progress)."""
    s = get_status(db_path, arxiv_id)
    if s is None:
        return False
    return s in PROCESSED_STATUSES or s in IN_PROGRESS_STATUSES


def get_paper(db_path: str | Path, arxiv_id: str) -> dict[str, Any] | None:
    """Return full row as dict or None."""
    with _conn(db_path) as conn:
        cur = conn.execute("SELECT * FROM papers WHERE arxiv_id = ?", (arxiv_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return dict(row)
