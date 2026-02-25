"""
Load and validate config from YAML. Supports env overrides for secrets.
"""

import os
from pathlib import Path
from typing import Any

import yaml

# Env keys for overrides
ENV_MODEL_API_KEY = "OPENAI_API_KEY"
ENV_EMAIL_PASSWORD = "ARXIV_DIGEST_SMTP_PASSWORD"


def load_config(path: str | Path) -> dict[str, Any]:
    """Load config from YAML file. Apply env overrides for api_key and smtp_password."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not raw:
        raise ValueError("Config file is empty")

    # Apply env overrides
    if "model" in raw and os.environ.get(ENV_MODEL_API_KEY):
        raw["model"] = raw.get("model") or {}
        raw["model"]["api_key"] = os.environ[ENV_MODEL_API_KEY]
    if "email" in raw and os.environ.get(ENV_EMAIL_PASSWORD):
        raw["email"] = raw.get("email") or {}
        raw["email"]["smtp_password"] = os.environ[ENV_EMAIL_PASSWORD]

    validate_config(raw)
    return raw


def validate_config(c: dict[str, Any]) -> None:
    """Validate required sections and types. Raises ValueError on failure."""
    required_sections = ("arxiv", "model", "thresholds", "storage", "email")
    for key in required_sections:
        if key not in c:
            raise ValueError(f"config missing required section: {key}")

    arxiv_c = c["arxiv"]
    if not isinstance(arxiv_c.get("categories"), list) or not arxiv_c["categories"]:
        raise ValueError("config.arxiv.categories must be a non-empty list")
    if not isinstance(arxiv_c.get("max_results_per_category"), int):
        raise ValueError("config.arxiv.max_results_per_category must be an int")
    if arxiv_c.get("days_back") is not None and not isinstance(arxiv_c["days_back"], int):
        raise ValueError("config.arxiv.days_back must be an int or omitted")

    model_c = c["model"]
    for k in ("base_url", "model_name"):
        if not model_c.get(k):
            raise ValueError(f"config.model.{k} is required")
    if model_c.get("temperature") is not None and not isinstance(model_c["temperature"], (int, float)):
        raise ValueError("config.model.temperature must be numeric")
    if model_c.get("timeout_s") is not None and not isinstance(model_c["timeout_s"], int):
        raise ValueError("config.model.timeout_s must be an int")

    th = c["thresholds"]
    if "relevance" not in th or not isinstance(th["relevance"], (int, float)):
        raise ValueError("config.thresholds.relevance must be a number in [0,1]")
    if not 0 <= th["relevance"] <= 1:
        raise ValueError("config.thresholds.relevance must be in [0,1]")

    storage_c = c["storage"]
    for k in ("db_path", "pdf_dir", "text_dir"):
        if not storage_c.get(k):
            raise ValueError(f"config.storage.{k} is required")
    if "save_text" not in storage_c:
        storage_c["save_text"] = False
    if not isinstance(storage_c["save_text"], bool):
        raise ValueError("config.storage.save_text must be bool")

    email_c = c["email"]
    for k in ("smtp_host", "smtp_port", "from_addr", "to_addr"):
        if not email_c.get(k):
            raise ValueError(f"config.email.{k} is required")
    if not isinstance(email_c.get("smtp_port"), int):
        raise ValueError("config.email.smtp_port must be an int")
    if "use_tls" not in email_c:
        email_c["use_tls"] = True
    if not isinstance(email_c["use_tls"], bool):
        raise ValueError("config.email.use_tls must be bool")

    # Optional: Google Scholar (enabled + queries; may get captcha without browser)
    if "scholar" in c:
        sc = c["scholar"]
        if not isinstance(sc.get("enabled"), bool):
            raise ValueError("config.scholar.enabled must be bool when scholar section is present")
        if sc.get("enabled") and (not isinstance(sc.get("queries"), list) or not sc["queries"]):
            raise ValueError("config.scholar.queries must be a non-empty list when scholar is enabled")

    # Optional: Semantic Scholar API (no browser, no captcha; recommended if Scholar fails)
    if "semantic_scholar" in c:
        ss = c["semantic_scholar"]
        if not isinstance(ss.get("enabled"), bool):
            raise ValueError("config.semantic_scholar.enabled must be bool when section is present")
        if ss.get("enabled") and (not isinstance(ss.get("queries"), list) or not ss["queries"]):
            raise ValueError("config.semantic_scholar.queries must be a non-empty list when enabled")
