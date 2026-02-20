"""Tests for config loading and validation."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from arxiv_digest.config import load_config, validate_config, ENV_MODEL_API_KEY


def test_validate_config_minimal():
    c = {
        "arxiv": {"categories": ["cs.LG"], "max_results_per_category": 10, "days_back": 1},
        "model": {"base_url": "http://localhost/v1", "model_name": "test", "api_key": "x"},
        "thresholds": {"relevance": 0.8},
        "storage": {"db_path": "x.db", "pdf_dir": "pdfs", "text_dir": "text", "save_text": False},
        "email": {
            "smtp_host": "smtp.x.com", "smtp_port": 587,
            "from_addr": "a@x.com", "to_addr": "b@x.com", "use_tls": True,
        },
    }
    validate_config(c)
    assert c["storage"]["save_text"] is False


def test_validate_config_relevance_bounds():
    c = {
        "arxiv": {"categories": ["cs.LG"], "max_results_per_category": 10},
        "model": {"base_url": "http://x", "model_name": "m", "api_key": "k"},
        "thresholds": {"relevance": 1.5},
        "storage": {"db_path": "d", "pdf_dir": "p", "text_dir": "t", "save_text": False},
        "email": {"smtp_host": "h", "smtp_port": 25, "from_addr": "a", "to_addr": "b", "use_tls": False},
    }
    with pytest.raises(ValueError, match="0,1"):
        validate_config(c)


def test_load_config_missing_file():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.yaml")


def test_load_config_env_override(monkeypatch):
    monkeypatch.setenv(ENV_MODEL_API_KEY, "env-key-123")
    fd, path = tempfile.mkstemp(suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump({
                "arxiv": {"categories": ["cs.LG"], "max_results_per_category": 5},
                "model": {"base_url": "http://x", "model_name": "m", "api_key": "file-key"},
                "thresholds": {"relevance": 0.7},
                "storage": {"db_path": "d", "pdf_dir": "p", "text_dir": "t", "save_text": False},
                "email": {"smtp_host": "h", "smtp_port": 25, "from_addr": "a", "to_addr": "b", "use_tls": False},
            }, f, default_flow_style=False)
        cfg = load_config(path)
        assert cfg["model"]["api_key"] == "env-key-123"
    finally:
        os.unlink(path)
