"""
OpenAI-compatible API client for chat completions. Retries with exponential backoff.
"""

import json
import logging
import time
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)


def _strip_think_tags(s: str) -> str:
    """Remove <think>...</think> block if present (Qwen etc. output reasoning in think tags)."""
    lower = s.lstrip()
    if lower.startswith("<think>"):
        close_tag = "</" + "think>"
        end = s.find(close_tag)
        if end != -1:
            s = s[end + len(close_tag) :].lstrip()
        else:
            s = s[7:].lstrip()
    return s


def _extract_json_object(s: str) -> str:
    """Find first { and matching } to extract a single JSON object."""
    start = s.find("{")
    if start == -1:
        raise ValueError("No '{' found in model output")
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    raise ValueError("No matching '}' for JSON object")


def _normalize_json_raw(raw: str) -> str:
    """Strip think tags, markdown fences, then extract JSON for json.loads."""
    if not raw or not raw.strip():
        raise ValueError("Model returned empty or whitespace-only content")
    s = raw.strip()
    s = _strip_think_tags(s)
    s = s.strip()
    if not s:
        raise ValueError("Model returned only think/reasoning, no JSON")
    if s.startswith("```"):
        lines = s.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    if not s.startswith("{"):
        s = _extract_json_object(s)
    return s


def chat_completion(
    client: OpenAI,
    model_name: str,
    messages: list[dict[str, str]],
    temperature: float = 0,
    max_tokens: int = 4096,
    timeout_s: int = 120,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> str:
    """
    Call /chat/completions. Returns content string. Raises on final failure.
    """
    last_err = None
    for attempt in range(max_retries):
        try:
            r = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout_s,
            )
            if r.choices and len(r.choices) > 0:
                return (r.choices[0].message.content or "").strip()
            raise ValueError("Empty completion")
        except Exception as e:
            last_err = e
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Model API call failed (attempt %s/%s): %s; retry in %.1fs",
                attempt + 1, max_retries, e, delay,
            )
            if attempt < max_retries - 1:
                time.sleep(delay)
    raise last_err or RuntimeError("Model call failed")


def parse_stage1_json(raw: str, paper_id: str) -> dict[str, Any]:
    """
    Parse Stage-1 JSON. Validate and clamp relevance to [0,1].
    Raises ValueError on parse/schema failure.
    """
    try:
        s = _normalize_json_raw(raw)
    except ValueError as e:
        logger.debug("Stage1 raw (first 400 chars): %r", (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        logger.warning("Stage1 JSON parse error for %s; raw snippet: %r", paper_id, (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    if data.get("paper_id") != paper_id:
        data["paper_id"] = paper_id

    topics = data.get("topics")
    if not isinstance(topics, list):
        raise ValueError("Missing or invalid 'topics' array")
    for t in topics:
        if not isinstance(t, dict):
            raise ValueError("Each topic must be an object")
        r = t.get("relevance")
        if r is not None:
            try:
                t["relevance"] = max(0.0, min(1.0, float(r)))
            except (TypeError, ValueError):
                t["relevance"] = 0.0
    if "overall_relevance" in data and data["overall_relevance"] is not None:
        try:
            data["overall_relevance"] = max(0.0, min(1.0, float(data["overall_relevance"])))
        except (TypeError, ValueError):
            data["overall_relevance"] = 0.0
    if data.get("decision") not in ("keep", "drop"):
        data["decision"] = "drop"
    return data


def parse_stage2_json(raw: str, paper_id: str) -> dict[str, Any]:
    """
    Parse Stage-2 summary JSON. Validate types and clamp relevance.
    """
    try:
        s = _normalize_json_raw(raw)
    except ValueError as e:
        logger.debug("Stage2 raw (first 400 chars): %r", (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        logger.warning("Stage2 JSON parse error for %s; raw snippet: %r", paper_id, (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    data["paper_id"] = data.get("paper_id") or paper_id

    for key in ("key_challenges", "assumptions_limitations", "evidence_results", "takeaways"):
        val = data.get(key)
        if val is None:
            data[key] = []
        elif not isinstance(val, list):
            data[key] = [str(val)]
        else:
            data[key] = [str(x) for x in val]

    if "topics" in data and isinstance(data["topics"], list):
        for t in data["topics"]:
            if isinstance(t, dict) and "relevance" in t:
                try:
                    t["relevance"] = max(0.0, min(1.0, float(t["relevance"])))
                except (TypeError, ValueError):
                    t["relevance"] = 0.0

    for key in ("problem", "motivation", "approach", "title", "categories", "published"):
        if data.get(key) is None:
            data[key] = "" if key != "categories" else []
        elif key == "categories" and not isinstance(data[key], list):
            data["categories"] = [str(data["categories"])]
    return data


def build_stage1_prompt(topics_config: list[dict], paper: dict[str, Any]) -> list[dict[str, str]]:
    """Build messages for Stage-1 classification + relevance."""
    topics_desc = "\n".join(
        f"- id: {t['id']}, name: {t['name']}, description: {t['description']}"
        for t in topics_config
    )
    paper_blob = (
        f"Title: {paper['title']}\n"
        f"Categories: {', '.join(paper.get('categories', []))}\n"
        f"Published: {paper.get('published', '')}\n"
        f"Abstract: {paper.get('abstract', '')}"
    )
    system = (
        "You are a classifier. For each paper, assign each topic a relevance score in [0, 1] "
        "and give a short reason (<=40 words). Output ONLY a single valid JSON object: no <think>, "
        "no reasoning text, no markdown, no explanation. Start your response with {."
    )
    user = (
        f"Topics:\n{topics_desc}\n\nPaper:\n{paper_blob}\n\n"
        "Output JSON: {\"paper_id\": \"<arxiv_id>\", \"topics\": [{\"topic_id\": \"...\", \"relevance\": 0.0-1.0, \"reason\": \"...\"}, ...], "
        "\"overall_relevance\": 0.0-1.0, \"decision\": \"keep\" or \"drop\"}. "
        "decision must be \"keep\" if any topic relevance >= 0.8 else \"drop\"."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_stage2_prompt(
    paper_metadata: dict[str, Any],
    full_text: str,
    stage1_topics: list[dict],
    max_chars: int = 120000,
) -> list[dict[str, str]]:
    """Build messages for Stage-2 structured summary. Truncate full_text if needed."""
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n\n[TRUNCATED]"
    meta = (
        f"Title: {paper_metadata.get('title', '')}\n"
        f"Categories: {paper_metadata.get('categories', [])}\n"
        f"Published: {paper_metadata.get('published', '')}\n"
        f"Stage-1 topics: {json.dumps(stage1_topics)}"
    )
    system = (
        "You produce a structured summary in JSON only. Be concise and faithful. "
        "If evidence is missing, say 'not clearly reported'. Output ONLY valid JSON, no markdown."
    )
    user = (
        f"Paper metadata:\n{meta}\n\nFull text (extract):\n{full_text}\n\n"
        "Output JSON with: paper_id, title, categories, published, topics (from stage1), "
        "problem, motivation, key_challenges (array), approach, assumptions_limitations (array), "
        "evidence_results (array), takeaways (exactly 3 bullets)."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
