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


def _strip_leading_reasoning(s: str) -> str:
    """Drop leading reasoning text (e.g. 'Thinking Process:...') before first { or [."""
    s = s.strip()
    for prefix in ("Thinking Process:", "Thinking:", "Analysis:", "Reasoning:", "Process:"):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix) :].lstrip()
            break
    idx_brace = s.find("{")
    idx_bracket = s.find("[")
    if idx_brace == -1 and idx_bracket == -1:
        return s
    if idx_brace >= 0 and (idx_bracket == -1 or idx_brace <= idx_bracket):
        return s[idx_brace:].strip()
    return s[idx_bracket:].strip()


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
    """Strip think tags, leading reasoning text, markdown fences, then extract JSON for json.loads."""
    if not raw or not raw.strip():
        raise ValueError("Model returned empty or whitespace-only content")
    s = raw.strip()
    s = _strip_think_tags(s)
    s = _strip_leading_reasoning(s)
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


def _extract_json_array(s: str) -> str:
    """Find first [ and matching ] to extract a JSON array."""
    start = s.find("[")
    if start == -1:
        raise ValueError("No '[' found in model output")
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "[":
            depth += 1
        elif s[i] == "]":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    raise ValueError("No matching ']' for JSON array")


def _normalize_json_raw_array(raw: str) -> str:
    """Strip think tags, leading reasoning text, markdown fences, then extract a JSON array."""
    if not raw or not raw.strip():
        raise ValueError("Model returned empty content")
    s = raw.strip()
    s = _strip_think_tags(s)
    s = _strip_leading_reasoning(s)
    s = s.strip()
    if not s:
        raise ValueError("Model returned only think/reasoning")
    if s.startswith("```"):
        lines = s.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    if not s.startswith("["):
        s = _extract_json_array(s)
    return s


# 后台程序重启 LLM 的等待时间（秒），在所有重试耗尽后等待一次
SERVER_RESTART_WAIT_S = 600


def chat_completion(
    client: OpenAI,
    model_name: str,
    messages: list[dict[str, str]],
    temperature: float = 0,
    max_tokens: int = 4096,
    timeout_s: int = 120,
    max_retries: int = 3,
    base_delay: float = 2.0,
    server_restart_wait_s: int = SERVER_RESTART_WAIT_S,
) -> str:
    """
    Call /chat/completions. Returns content string. Raises on final failure.

    Retry strategy:
    - Up to max_retries attempts with exponential backoff (base_delay * 2^attempt).
    - After all retries fail, waits server_restart_wait_s for LLM server to restart,
      then makes one final attempt.
    - Set server_restart_wait_s=0 to skip the long wait (e.g. for parallel Stage 1).
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
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Model API call failed (attempt %d/%d): %s; retry in %.1fs",
                    attempt + 1, max_retries, e, delay,
                )
                time.sleep(delay)
            else:
                logger.warning(
                    "Model API call failed (attempt %d/%d): %s",
                    attempt + 1, max_retries, e,
                )

    # All retries exhausted — optionally wait for server restart then try once more
    if server_restart_wait_s > 0:
        logger.warning(
            "All %d retries exhausted; waiting %ds for potential LLM server restart",
            max_retries, server_restart_wait_s,
        )
        time.sleep(server_restart_wait_s)
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
        except Exception as e:
            last_err = e
            logger.warning("Final attempt after server restart wait also failed: %s", e)

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
    # Normalise paper_id (model may return number or string)
    raw_pid = data.get("paper_id")
    data["paper_id"] = str(raw_pid) if raw_pid is not None else paper_id
    if data["paper_id"] != paper_id:
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


def build_stage1_batch_prompt(
    topics_config: list[dict],
    papers: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build a single prompt that classifies a batch of papers in one LLM call.
    More efficient than calling build_stage1_prompt N times.
    """
    topics_desc = "\n".join(
        f"- id: {t['id']}, name: {t['name']}, description: {t['description']}"
        for t in topics_config
    )
    papers_blob = "\n\n".join(
        f"Paper {i + 1} (id: \"{p['arxiv_id']}\"):\n"
        f"Title: {p.get('title', '')}\n"
        f"Categories: {', '.join(p.get('categories', []))}\n"
        f"Abstract: {p.get('abstract', '')}"
        for i, p in enumerate(papers)
    )
    n = len(papers)
    system = (
        "You are a batch classifier. For each paper in the list, assign each topic a relevance "
        "score in [0, 1] with a short reason (<=25 words). "
        "Output ONLY a single valid JSON array, one object per paper, in input order. "
        "No <think>, no reasoning text, no markdown. Start your response with [."
    )
    user = (
        f"Topics:\n{topics_desc}\n\n"
        f"Papers to classify ({n} total):\n{papers_blob}\n\n"
        f"Output a JSON array with exactly {n} objects in the same order as above:\n"
        "[{\"paper_id\": \"<id>\", \"topics\": [{\"topic_id\": \"...\", "
        "\"relevance\": 0.0-1.0, \"reason\": \"...\"}, ...], "
        "\"overall_relevance\": 0.0-1.0, \"decision\": \"keep\" or \"drop\"}, ...]"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_stage1_batch_json(
    raw: str,
    papers: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """Parse batch Stage-1 JSON array. Returns list of (arxiv_id, stage1_dict).

    Matches results to input papers by paper_id field first, then by position.
    Raises ValueError if JSON is unparseable (caller should fall back to individual calls).
    """
    s = _normalize_json_raw_array(raw)
    data = json.loads(s)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array, got {type(data).__name__}")

    id_to_paper = {p["arxiv_id"]: p for p in papers}
    matched: dict[str, dict] = {}

    # Pass 1: match by paper_id field
    for item in data:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("paper_id", ""))
        if pid in id_to_paper and pid not in matched:
            item["paper_id"] = pid
            _clamp_stage1_item(item)
            matched[pid] = item

    # Pass 2: positional fallback for unmatched papers
    unmatched = [p for p in papers if p["arxiv_id"] not in matched]
    if unmatched:
        pos_items = [item for item in data if isinstance(item, dict)]
        for paper, item in zip(unmatched, pos_items[len(matched):]):
            pid = paper["arxiv_id"]
            item["paper_id"] = pid
            _clamp_stage1_item(item)
            matched[pid] = item

    if len(matched) < len(papers):
        logger.warning(
            "Batch Stage1 matched %d/%d papers after positional fallback",
            len(matched), len(papers),
        )

    # Return in original input order
    return [(p["arxiv_id"], matched[p["arxiv_id"]]) for p in papers if p["arxiv_id"] in matched]


def _clamp_stage1_item(item: dict[str, Any]) -> None:
    """In-place: clamp relevance scores and normalise decision field."""
    for t in item.get("topics", []):
        if isinstance(t, dict) and "relevance" in t:
            try:
                t["relevance"] = max(0.0, min(1.0, float(t["relevance"])))
            except (TypeError, ValueError):
                t["relevance"] = 0.0
    if "overall_relevance" in item and item["overall_relevance"] is not None:
        try:
            item["overall_relevance"] = max(0.0, min(1.0, float(item["overall_relevance"])))
        except (TypeError, ValueError):
            item["overall_relevance"] = 0.0
    if item.get("decision") not in ("keep", "drop"):
        item["decision"] = "drop"


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
) -> list[dict[str, str]]:
    """Build messages for Stage-2 structured summary.
    Truncation is handled upstream by pdf_utils.extract_key_sections(); no further
    truncation is done here so the smart section-aware cut is preserved.
    """
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
