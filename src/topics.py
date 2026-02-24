"""
Topic schema: load and validate topics from YAML.
"""

from pathlib import Path
from typing import Any

import yaml


def load_topics(path: str | Path) -> list[dict[str, Any]]:
    """Load topics from YAML. Expects key 'topics' with list of topic dicts."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Topics file not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "topics" not in data:
        raise ValueError("Topics file must contain a 'topics' list")

    topics = data["topics"]
    if not isinstance(topics, list):
        raise ValueError("topics must be a list")

    seen_ids: set[str] = set()
    for i, t in enumerate(topics):
        if not isinstance(t, dict):
            raise ValueError(f"topic[{i}] must be a dict")
        if "id" not in t or not str(t["id"]).strip():
            raise ValueError(f"topic[{i}] must have non-empty 'id'")
        if "name" not in t or not str(t["name"]).strip():
            raise ValueError(f"topic[{i}] must have non-empty 'name'")
        tid = str(t["id"]).strip()
        if tid in seen_ids:
            raise ValueError(f"Duplicate topic id: {tid}")
        seen_ids.add(tid)
        t["id"] = tid
        t["name"] = str(t["name"]).strip()
        t["description"] = str(t.get("description", "")).strip()
        t["keywords"] = t.get("keywords") or []
        if not isinstance(t["keywords"], list):
            t["keywords"] = []

    return topics
