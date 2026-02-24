"""Tests for topics loading."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from arxiv_digest.topics import load_topics


def test_load_topics_minimal():
    fd, path = tempfile.mkstemp(suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump({
                "topics": [
                    {"id": "a", "name": "Topic A", "description": "Desc A"},
                    {"id": "b", "name": "Topic B", "description": ""},
                ]
            }, f, default_flow_style=False)
        t = load_topics(path)
        assert len(t) == 2
        assert t[0]["id"] == "a" and t[0]["name"] == "Topic A"
        assert t[1]["keywords"] == []
    finally:
        Path(path).unlink()


def test_load_topics_duplicate_id():
    fd, path = tempfile.mkstemp(suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump({
                "topics": [
                    {"id": "x", "name": "X", "description": ""},
                    {"id": "x", "name": "Y", "description": ""},
                ]
            }, f, default_flow_style=False)
        with pytest.raises(ValueError, match="Duplicate"):
            load_topics(path)
    finally:
        Path(path).unlink()


def test_load_topics_missing_file():
    with pytest.raises(FileNotFoundError):
        load_topics("/nonexistent/topics.yaml")
