"""Tests for DB helpers."""

import tempfile
from pathlib import Path

import pytest

from arxiv_digest import db


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d) / "test.db"


def test_ensure_db(db_path):
    db.ensure_db(db_path)
    assert db_path.exists()
    db.ensure_db(db_path)  # idempotent


def test_upsert_and_status(db_path):
    db.ensure_db(db_path)
    db.upsert_paper_metadata(db_path, "2401.12345", "Test Title", "cs.LG", db.NEW)
    assert db.get_status(db_path, "2401.12345") == db.NEW
    db.upsert_paper_metadata(db_path, "2401.12345", "Updated Title", "cs.LG,cs.AI")
    assert db.get_status(db_path, "2401.12345") == db.NEW


def test_mark_status(db_path):
    db.ensure_db(db_path)
    db.upsert_paper_metadata(db_path, "2401.11111", "T", "cs.LG", db.NEW)
    db.mark_status(db_path, "2401.11111", db.STAGE1_OK, stage1_json='{"x":1}')
    assert db.get_status(db_path, "2401.11111") == db.STAGE1_OK
    row = db.get_paper(db_path, "2401.11111")
    assert row is not None
    assert "stage1_json" in row and "x" in (row["stage1_json"] or "")


def test_is_processed(db_path):
    db.ensure_db(db_path)
    db.upsert_paper_metadata(db_path, "a", "T", "c", db.NEW)
    assert db.is_processed(db_path, "a") is False
    db.mark_status(db_path, "a", db.EMAILED)
    assert db.is_processed(db_path, "a") is True
    assert db.is_processed(db_path, "nonexistent") is False


def test_is_in_progress_or_processed(db_path):
    db.ensure_db(db_path)
    assert db.is_in_progress_or_processed(db_path, "x") is False
    db.upsert_paper_metadata(db_path, "x", "T", "c", db.STAGE1_OK)
    assert db.is_in_progress_or_processed(db_path, "x") is True
