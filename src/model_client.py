"""
OpenAI-compatible API client for chat completions. Retries with exponential backoff.
"""

import ast
import json
import logging
import re
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
    """Drop leading reasoning text (e.g. 'Thinking Process:...') before first real JSON start ({ or [).
    Skip lone { that is part of text like 'Start with `{`' (brace followed by backtick)."""
    s = s.strip()
    for prefix in ("Thinking Process:", "Thinking:", "Analysis:", "Reasoning:", "Process:"):
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix) :].lstrip()
            break
    # Find first { that looks like start of JSON: { then optional space then " or '
    idx_brace = -1
    for i, c in enumerate(s):
        if c == "{":
            rest = s[i + 1 :].lstrip()
            # Skip { that is inside "Start with `{`" (rest starts with backtick)
            if rest.startswith("`"):
                continue
            idx_brace = i
            break
    idx_bracket = s.find("[")
    if idx_brace == -1 and idx_bracket == -1:
        return s
    if idx_brace >= 0 and (idx_bracket == -1 or idx_brace <= idx_bracket):
        return s[idx_brace:].strip()
    return s[idx_bracket:].strip()


def _fix_single_quoted_keys(s: str) -> str:
    """Convert Python-style 'key': to JSON "key": so json.loads accepts it."""
    return re.sub(r"'([^']*)'\s*:", r'"\1":', s)


def _fix_missing_colon_between_quoted(s: str) -> str:
    """Insert missing colon when model outputs \"key\" \"value\" instead of \"key\": \"value\"."""
    # Only fix known Stage1 keys so we don't break string values that contain " \" "
    keys = r"paper_id|topic_id|relevance|reason|decision|overall_relevance|topics"
    return re.sub(r'"(' + keys + r')"\s+"', r'"\1": "', s)


def _replace_backtick_strings(s: str) -> str:
    """Replace `identifier` with "identifier" so JSON/ast can parse (model often outputs `llm-opt` etc)."""
    return re.sub(r"`([^`]*)`", r'"\1"', s)


def _escape_control_in_double_quoted_strings(s: str) -> str:
    """Escape raw newline/return/tab inside double-quoted strings so json.loads accepts (model may emit literal newlines in values)."""
    result: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == '"' and (i == 0 or s[i - 1] != "\\"):
            result.append(s[i])
            i += 1
            while i < len(s):
                c = s[i]
                if c == '"' and s[i - 1] != "\\":
                    result.append(c)
                    i += 1
                    break
                if c == "\\":
                    result.append(c)
                    i += 1
                    if i < len(s):
                        result.append(s[i])
                        i += 1
                    continue
                if c in "\n\r\t":
                    result.append("\\n" if c == "\n" else "\\r" if c == "\r" else "\\t")
                    i += 1
                    continue
                result.append(c)
                i += 1
            continue
        result.append(s[i])
        i += 1
    return "".join(result)


def _try_close_truncated_json(s: str) -> str:
    """If s is truncated (unterminated string or missing braces), try to close it for parsing."""
    # Count unclosed structure
    open_braces = s.count("{") - s.count("}")
    open_brackets = s.count("[") - s.count("]")
    if open_braces <= 0 and open_brackets <= 0:
        return s
    # If we're inside an unclosed string (ends on odd number of quotes outside of escaped), close the string first
    in_double = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == '"' and (i == 0 or s[i - 1] != "\\"):
            in_double = not in_double
        i += 1
    if in_double:
        s = s + '"'
    s = s + ("]" * open_brackets) + ("}" * open_braces)
    return s


def _try_parse_json_or_python_dict(s: str) -> dict[str, Any] | list[Any]:
    """Try json.loads; on failure try ast.literal_eval (handles single-quoted keys/values) and control-char escape."""
    s = _replace_backtick_strings(s)
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        err_str = str(e).lower()
        if "control character" in err_str:
            s = _escape_control_in_double_quoted_strings(s)
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                pass
        if "unterminated string" in err_str:
            try:
                closed = _try_close_truncated_json(s)
                return json.loads(closed)
            except json.JSONDecodeError:
                pass
        if "expecting" in err_str and "delimiter" in err_str and ":" in err_str:
            try:
                fixed = _fix_missing_colon_between_quoted(s)
                if fixed != s:
                    return json.loads(fixed)
            except json.JSONDecodeError:
                pass
    # Remove trailing commas so ast.literal_eval accepts
    s_clean = re.sub(r",\s*}", "}", s)
    s_clean = re.sub(r",\s*]", "]", s_clean)
    try:
        out = ast.literal_eval(s_clean)
        if isinstance(out, (dict, list)):
            return out
    except (ValueError, SyntaxError):
        pass
    s = _fix_single_quoted_keys(s)
    return json.loads(s)


def _extract_first_json_object(s: str) -> str:
    """Extract substring from first { to matching }; no skip logic. For aggressive fallback."""
    start = s.find("{")
    if start == -1:
        raise ValueError("No '{' found")
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start : i + 1]
    last_brace = s.rfind("}", start)
    if last_brace > start:
        return s[start : last_brace + 1]
    raise ValueError("No matching '}' for JSON object")


def _extract_json_object(s: str) -> str:
    """Find JSON object: skip prompt example (contains "<arxiv_id>"). Prefer one that contains "topics" (real schema); else last without placeholder."""
    skip_marker = "<arxiv_id>"
    pos = 0
    best: str | None = None
    while True:
        start = s.find("{", pos)
        if start == -1:
            if best is not None:
                return best
            raise ValueError("No '{' found in model output")
        depth = 0
        end = -1
        for i in range(start, len(s)):
            if s[i] == "{":
                depth += 1
            elif s[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            last_brace = s.rfind("}", start)
            if last_brace > start:
                end = last_brace + 1
            else:
                end = len(s)
        candidate = s[start:end]
        if skip_marker not in candidate:
            # Prefer object that has both paper_id and topics keys (Stage1 schema)
            if re.search(r'["\']paper_id["\']\s*:', candidate) and re.search(r'["\']topics["\']\s*:', candidate):
                return candidate
            best = candidate
        pos = end
        if end >= len(s):
            break
    if best is not None:
        return best
    raise ValueError("No '{' found in model output")


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
    # Always extract via _extract_json_object so we skip prompt example {"paper_id": "<arxiv_id>", ...}
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
    extra_body: dict[str, Any] | None = None,
) -> str:
    """
    Call /chat/completions. Returns content string. Raises on final failure.

    extra_body: passed to the API (e.g. vLLM chat_template_kwargs).
    Returns only message.content (final answer). When vLLM is started with
    --reasoning-parser qwen3, thinking is in message.reasoning and content
    is the final answer only; without the parser, content may contain both.
    """
    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": timeout_s,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body

    last_err = None
    for attempt in range(max_retries):
        try:
            r = client.chat.completions.create(**kwargs)
            if r.choices and len(r.choices) > 0:
                msg = r.choices[0].message
                # vLLM with --reasoning-parser: message.reasoning = thinking, message.content = final answer only
                if getattr(msg, "reasoning", None):
                    logger.debug("Response has reasoning + content; using content only for parsing")
                return (msg.content or "").strip()
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
            r = client.chat.completions.create(**kwargs)
            if r.choices and len(r.choices) > 0:
                msg = r.choices[0].message
                return (msg.content or "").strip()
        except Exception as e:
            last_err = e
            logger.warning("Final attempt after server restart wait also failed: %s", e)

    raise last_err or RuntimeError("Model call failed")


def _validate_stage1_data(data: dict[str, Any], paper_id: str) -> dict[str, Any]:
    """
    Validate and normalize Stage1 dict: paper_id, topics (list of dicts), relevance clamp, decision.
    Call this after you have a dict (from any extraction path). Raises ValueError on invalid schema.
    """
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    raw_pid = data.get("paper_id")
    data["paper_id"] = str(raw_pid) if raw_pid is not None else paper_id
    if data["paper_id"] != paper_id:
        data["paper_id"] = paper_id

    topics_raw = data.get("topics")
    if not isinstance(topics_raw, list):
        raise ValueError("Missing or invalid 'topics' array")
    topics: list[dict[str, Any]] = []
    for t in topics_raw:
        if isinstance(t, dict):
            # Accept topic_id from id/topic alias; coerce relevance from string
            tid = t.get("topic_id") or t.get("id") or t.get("topic")
            if tid is not None:
                t = dict(t)
                t["topic_id"] = str(tid)
            else:
                t = dict(t)
                t["topic_id"] = str(t.get("topic_id", ""))
            topics.append(t)
        elif isinstance(t, (list, tuple)) and len(t) >= 2:
            try:
                topics.append({
                    "topic_id": str(t[0]),
                    "relevance": max(0.0, min(1.0, float(t[1]))),
                    "reason": str(t[2]) if len(t) > 2 else "",
                })
            except (TypeError, ValueError):
                pass
    if not topics:
        raise ValueError("Missing or invalid 'topics' array (no valid topic objects)")
    data["topics"] = topics
    for t in topics:
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
        data = _try_parse_json_or_python_dict(s)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Stage1 JSON parse error for %s; raw snippet: %r", paper_id, (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e
    return _validate_stage1_data(data, paper_id)


def try_parse_stage1_aggressive(raw: str, paper_id: str) -> tuple[dict[str, Any] | None, Exception | None]:
    """
    Try multiple extraction/parse strategies. Returns (data, None) on success, (None, error) on failure.
    Use when parse_stage1_json failed so we can still recover without another LLM call.
    """
    last_err: Exception = ValueError("Parse failed")
    # 1) Standard path
    try:
        return parse_stage1_json(raw, paper_id), None
    except ValueError as e:
        last_err = e

    # 2) Strip to first { ... last } and parse (no skip of prompt example)
    try:
        s = raw.strip()
        s = _strip_think_tags(s)
        s = _strip_leading_reasoning(s)
        s = _extract_first_json_object(s)
        data = _try_parse_json_or_python_dict(s)
        return _validate_stage1_data(data, paper_id), None
    except Exception as e:
        last_err = e

    # 3) Apply backtick/single-quote fixes to full raw, then first-object extract
    try:
        s = _replace_backtick_strings(raw.strip())
        s = _strip_think_tags(s)
        s = _strip_leading_reasoning(s)
        if s.startswith("```"):
            lines = s.split("\n")
            if lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        s = _extract_first_json_object(s)
        s = _fix_single_quoted_keys(s)
        data = json.loads(s)
        return _validate_stage1_data(data, paper_id), None
    except Exception as e:
        last_err = e

    # 4) Literal first { to last } in raw (no strip reasoning)
    try:
        start = raw.find("{")
        if start != -1:
            end = raw.rfind("}")
            if end > start:
                s = raw[start : end + 1]
                data = _try_parse_json_or_python_dict(s)
                return _validate_stage1_data(data, paper_id), None
    except Exception as e:
        last_err = e

    return None, last_err


def _validate_stage2_data(data: dict[str, Any], paper_id: str) -> dict[str, Any]:
    """Validate and fill Stage2 dict. Call after you have a dict from any extraction path."""
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    # Always force the authoritative paper_id (LLM often outputs "arXiv:..." or garbage)
    data["paper_id"] = paper_id
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


def parse_stage2_json(raw: str, paper_id: str) -> dict[str, Any]:
    """Parse Stage-2 summary JSON. Validate types and clamp relevance."""
    try:
        s = _normalize_json_raw(raw)
    except ValueError as e:
        logger.debug("Stage2 raw (first 400 chars): %r", (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e
    try:
        data = _try_parse_json_or_python_dict(s)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Stage2 JSON parse error for %s; raw snippet: %r", paper_id, (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e
    return _validate_stage2_data(data, paper_id)


def try_parse_stage2_aggressive(raw: str, paper_id: str) -> tuple[dict[str, Any] | None, Exception | None]:
    """Try multiple extraction strategies for Stage2. Returns (data, None) or (None, error)."""
    last_err: Exception = ValueError("Parse failed")
    try:
        return parse_stage2_json(raw, paper_id), None
    except ValueError as e:
        last_err = e
    try:
        s = raw.strip()
        s = _strip_think_tags(s)
        s = _strip_leading_reasoning(s)
        s = _extract_first_json_object(s)
        data = _try_parse_json_or_python_dict(s)
        return _validate_stage2_data(data, paper_id), None
    except Exception as e:
        last_err = e
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            data = _try_parse_json_or_python_dict(raw[start : end + 1])
            return _validate_stage2_data(data, paper_id), None
    except Exception as e:
        last_err = e
    return None, last_err


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
        "You are a batch classifier. For each paper, assign each topic a relevance "
        "score in [0, 1] with a short reason (<=25 words). "
        "Your entire reply must be exactly one valid JSON array: no 'Thinking Process', "
        "no <think>, no reasoning, no markdown. Use double quotes for all keys and strings. "
        "Start your response with [."
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
    try:
        data = _try_parse_json_or_python_dict(s)
    except (json.JSONDecodeError, ValueError):
        raise ValueError("Invalid JSON: unparseable batch array") from None
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
        "and give a short reason (<=40 words). Your entire reply must be exactly one valid JSON object: "
        "no 'Thinking Process', no <think>, no reasoning, no markdown, no text before or after. "
        "Use double quotes for all keys and strings. Start your response with {."
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
        "All text values (problem, motivation, key_challenges, approach, "
        "assumptions_limitations, evidence_results, takeaways) MUST be written in 简体中文. "
        "If evidence is missing, say '未明确报告'. Output ONLY valid JSON, no markdown."
    )
    user = (
        f"Paper metadata:\n{meta}\n\nFull text (extract):\n{full_text}\n\n"
        "Output JSON with: paper_id, title, categories, published, topics (from stage1), "
        "problem, motivation, key_challenges (array), approach, assumptions_limitations (array), "
        "evidence_results (array), takeaways (exactly 3 bullets). "
        "All descriptive text fields must be in 简体中文."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    s = str(value).strip()
    return [s] if s else []


def _validate_stage3_data(data: dict[str, Any], paper_ids: list[str]) -> dict[str, Any]:
    """Validate Stage-3 briefing JSON and keep only known paper_ids."""
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    data["overview"] = str(data.get("overview") or "").strip()
    data["thinking"] = str(data.get("thinking") or data.get("reasoning") or "").strip()

    clusters_raw = data.get("clusters")
    if not isinstance(clusters_raw, list) or not clusters_raw:
        raise ValueError("Missing or empty 'clusters'")

    known = {str(pid) for pid in paper_ids if pid}
    seen: set[str] = set()
    clusters: list[dict[str, Any]] = []

    for i, raw_cluster in enumerate(clusters_raw):
        if not isinstance(raw_cluster, dict):
            continue
        papers: list[dict[str, str]] = []
        for item in raw_cluster.get("papers") or []:
            pid = ""
            one_liner = ""
            if isinstance(item, dict):
                pid = str(item.get("paper_id") or "").strip()
                one_liner = str(item.get("one_liner") or "").strip()
            elif isinstance(item, str):
                pid = item.strip()
            if not pid or pid not in known or pid in seen:
                continue
            seen.add(pid)
            papers.append({"paper_id": pid, "one_liner": one_liner})
        if not papers:
            continue

        must_read: list[dict[str, str]] = []
        for item in raw_cluster.get("must_read") or []:
            if isinstance(item, dict):
                pid = str(item.get("paper_id") or "").strip()
                why = str(item.get("why") or "").strip()
            elif isinstance(item, str):
                pid, why = item.strip(), ""
            else:
                continue
            if pid in known:
                must_read.append({"paper_id": pid, "why": why})

        close_reads: list[dict[str, str]] = []
        seen_reads: set[str] = set()
        for item in raw_cluster.get("close_reads") or []:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("paper_id") or "").strip()
            if not pid or pid not in known or pid in seen_reads:
                continue
            seen_reads.add(pid)
            close_reads.append({
                "paper_id": pid,
                "mechanism": str(item.get("mechanism") or "").strip(),
                "limitation": str(item.get("limitation") or "").strip(),
                "open_question": str(item.get("open_question") or "").strip(),
                "why_first": str(item.get("why_first") or "").strip(),
            })
            if len(close_reads) >= 3:
                break

        topic_ids = raw_cluster.get("topic_ids") or []
        if not isinstance(topic_ids, list):
            topic_ids = [topic_ids]
        topic_ids = [str(t).strip() for t in topic_ids if str(t).strip()]

        clusters.append({
            "cluster_id": str(raw_cluster.get("cluster_id") or f"cluster-{i + 1}"),
            "title": str(raw_cluster.get("title") or f"主题 {i + 1}").strip(),
            "topic_ids": topic_ids,
            "why_grouped": str(raw_cluster.get("why_grouped") or "").strip(),
            "narrative": str(raw_cluster.get("narrative") or "").strip(),
            "trends": _as_str_list(raw_cluster.get("trends")),
            "divergences": _as_str_list(raw_cluster.get("divergences")),
            "must_read": must_read,
            "close_reads": close_reads,
            "papers": papers,
        })

    if not clusters:
        raise ValueError("No valid clusters after validation")
    data["clusters"] = clusters
    return data


def parse_stage3_digest_json(raw: str, paper_ids: list[str]) -> dict[str, Any]:
    """Parse Stage-3 topic-briefing JSON."""
    try:
        s = _normalize_json_raw(raw)
    except ValueError as e:
        logger.debug("Stage3 raw (first 400 chars): %r", (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e
    try:
        data = _try_parse_json_or_python_dict(s)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Stage3 JSON parse error; raw snippet: %r", (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e
    return _validate_stage3_data(data, paper_ids)


def try_parse_stage3_aggressive(
    raw: str, paper_ids: list[str]
) -> tuple[dict[str, Any] | None, Exception | None]:
    """Try multiple extraction strategies for Stage-3. Returns (data, None) or (None, error)."""
    last_err: Exception = ValueError("Parse failed")
    try:
        return parse_stage3_digest_json(raw, paper_ids), None
    except ValueError as e:
        last_err = e
    try:
        s = raw.strip()
        s = _strip_think_tags(s)
        s = _strip_leading_reasoning(s)
        s = _extract_first_json_object(s)
        data = _try_parse_json_or_python_dict(s)
        return _validate_stage3_data(data, paper_ids), None
    except Exception as e:
        last_err = e
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            data = _try_parse_json_or_python_dict(raw[start : end + 1])
            return _validate_stage3_data(data, paper_ids), None
    except Exception as e:
        last_err = e
    return None, last_err


def build_stage3_digest_prompt(
    topics_config: list[dict],
    papers_compact: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build messages for Stage-3: cluster related topics and write a Chinese briefing."""
    topics_desc = "\n".join(
        f"- {t['id']}: {t['name']} — {t.get('description', '')}"
        for t in topics_config
    )
    papers_blob = json.dumps(papers_compact, ensure_ascii=False, indent=2)
    n = len(papers_compact)
    system = (
        "你是资深研究助手，负责把一批论文整理成「按研究线索阅读」的中文简报。"
        "先充分思考交叉主题、方法路线和阅读顺序，再输出最终 JSON。"
        "综述层做机制对比，不要写成「A做了X、B做了Y」的流水账。"
        "精读层只挑每条线索里真正值得拆的 2–3 篇，写清机制、局限和开放问题。"
        "其余论文只用 one_liner。"
        "最终回复必须是一个合法 JSON 对象：不要 markdown 代码块，不要在 JSON 前后写解释。"
        "所有字符串字段使用简体中文。"
    )
    user = (
        f"预设主题（可以合并，不要机械地每个主题开一节）：\n{topics_desc}\n\n"
        f"本批论文（共 {n} 篇，已含问题/方法/挑战/局限/证据）：\n{papers_blob}\n\n"
        "任务：\n"
        "1. 根据本批论文的实际内容，把相近 topic 聚成 2–6 条研究线索（cluster）；论文很少时可更少。\n"
        "2. narrative 写机制对比：共同假设、不同取舍、谁在推进哪一层、还缺什么。250–500 字。\n"
        "3. 每条线索选 2–3 篇做 close_reads（优先高相关、方法独特、或暴露缺口的）。"
        "mechanism 要落到数据结构/调度/放置/一致性等具体机制，不要口号。\n"
        "4. 其余论文只给一句 one_liner。禁止把每篇都写成独立报告。\n"
        "5. 每个 paper_id 必须且只能出现在一个 cluster 的 papers 里。\n\n"
        "输出 JSON：\n"
        '{"overview": "今日整体判断，3-6句，点出真正的技术张力",'
        ' "thinking": "交叉主题思考：哪些方向在汇合/分化，阅读顺序建议",'
        ' "clusters": [{'
        '"cluster_id": "英文短id", "title": "中文线索名",'
        ' "topic_ids": ["来自预设的id"], "why_grouped": "为何归为一簇",'
        ' "narrative": "机制对比综述，250-500字",'
        ' "trends": ["共同方向"], "divergences": ["分歧或不同路线"],'
        ' "must_read": [{"paper_id": "...", "why": "为何先读"}],'
        ' "close_reads": [{"paper_id": "...", "mechanism": "这篇实际改了什么机制",'
        ' "limitation": "没做什么 / 关键假设", "open_question": "由此能追的开放问题",'
        ' "why_first": "为何精读这篇"}],'
        ' "papers": [{"paper_id": "...", "one_liner": "一句话要点"}]}]}'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


_IDEA_DECISIONS = frozenset({"pursue", "watch", "drop"})
_SCOPE_VERDICTS = frozenset({"too_narrow", "just_right", "too_broad"})
_NOVELTY = frozenset({"incremental", "moderate", "high"})
_FEASIBILITY = frozenset({"low", "medium", "high"})
_RELATIONS = frozenset({"extends", "gaps", "overlaps", "contradicts"})


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _validate_idea_item(raw: dict[str, Any], paper_ids: list[str], idx: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    statement = str(raw.get("statement") or raw.get("idea") or "").strip()
    if not title and not statement:
        return None
    known = {str(pid) for pid in paper_ids if pid}

    related: list[dict[str, str]] = []
    for item in raw.get("related_papers") or []:
        if isinstance(item, dict):
            pid = str(item.get("paper_id") or "").strip()
            relation = str(item.get("relation") or "overlaps").strip().lower()
            if relation not in _RELATIONS:
                relation = "overlaps"
            if pid in known:
                related.append({
                    "paper_id": pid,
                    "relation": relation,
                    "note": str(item.get("note") or "").strip(),
                })
        elif isinstance(item, str) and item.strip() in known:
            related.append({"paper_id": item.strip(), "relation": "overlaps", "note": ""})

    external: list[dict[str, Any]] = []
    for item in raw.get("external_related") or []:
        if not isinstance(item, dict):
            continue
        ext_title = str(item.get("title") or "").strip()
        if not ext_title:
            continue
        external.append({
            "title": ext_title,
            "year": str(item.get("year") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "overlap": str(item.get("overlap") or "").strip(),
        })

    potential_raw = raw.get("potential") if isinstance(raw.get("potential"), dict) else {}
    novelty = str(potential_raw.get("novelty") or "moderate").strip().lower()
    feasibility = str(potential_raw.get("feasibility") or "medium").strip().lower()
    potential = {
        "score": _clamp01(potential_raw.get("score"), 0.5),
        "novelty": novelty if novelty in _NOVELTY else "moderate",
        "impact": str(potential_raw.get("impact") or "").strip(),
        "feasibility": feasibility if feasibility in _FEASIBILITY else "medium",
        "why": str(potential_raw.get("why") or "").strip(),
    }

    scope_raw = raw.get("scope") if isinstance(raw.get("scope"), dict) else {}
    scope_verdict = str(scope_raw.get("verdict") or "just_right").strip().lower()
    scope = {
        "verdict": scope_verdict if scope_verdict in _SCOPE_VERDICTS else "just_right",
        "horizon": str(scope_raw.get("horizon") or "").strip(),
        "why": str(scope_raw.get("why") or "").strip(),
    }

    decision = str(raw.get("decision") or "watch").strip().lower()
    topic_ids = raw.get("topic_ids") or []
    if not isinstance(topic_ids, list):
        topic_ids = [topic_ids]
    experiments = _as_str_list(raw.get("experiments"))[:4]
    risks = _as_str_list(raw.get("risks"))[:4]

    return {
        "idea_id": str(raw.get("idea_id") or f"idea-{idx + 1}"),
        "title": title or statement[:40],
        "topic_ids": [str(t).strip() for t in topic_ids if str(t).strip()],
        "statement": statement,
        "motivation": str(raw.get("motivation") or "").strip(),
        "gap": str(raw.get("gap") or "").strip(),
        "approach_sketch": str(raw.get("approach_sketch") or "").strip(),
        "experiments": experiments,
        "risks": risks,
        "not_a_reimplementation": str(raw.get("not_a_reimplementation") or "").strip(),
        "search_query": str(raw.get("search_query") or "").strip(),
        "related_papers": related,
        "external_related": external,
        "potential": potential,
        "scope": scope,
        "decision": decision if decision in _IDEA_DECISIONS else "watch",
        "decision_reason": str(raw.get("decision_reason") or "").strip(),
    }


def _validate_ideas_data(data: dict[str, Any], paper_ids: list[str]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    data["thinking"] = str(data.get("thinking") or data.get("overview") or "").strip()
    raw_ideas = data.get("ideas")
    if not isinstance(raw_ideas, list) or not raw_ideas:
        raise ValueError("Missing or empty 'ideas'")
    ideas: list[dict[str, Any]] = []
    for i, item in enumerate(raw_ideas):
        parsed = _validate_idea_item(item, paper_ids, i)
        if parsed:
            ideas.append(parsed)
    if not ideas:
        raise ValueError("No valid ideas after validation")
    data["ideas"] = ideas
    return data


def parse_ideas_json(raw: str, paper_ids: list[str]) -> dict[str, Any]:
    """Parse Stage-4 idea-exploration JSON."""
    try:
        s = _normalize_json_raw(raw)
    except ValueError as e:
        logger.debug("Ideas raw (first 400 chars): %r", (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e
    try:
        data = _try_parse_json_or_python_dict(s)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Ideas JSON parse error; raw snippet: %r", (raw or "")[:400])
        raise ValueError(f"Invalid JSON: {e}") from e
    return _validate_ideas_data(data, paper_ids)


def try_parse_ideas_aggressive(
    raw: str, paper_ids: list[str]
) -> tuple[dict[str, Any] | None, Exception | None]:
    last_err: Exception = ValueError("Parse failed")
    try:
        return parse_ideas_json(raw, paper_ids), None
    except ValueError as e:
        last_err = e
    try:
        s = raw.strip()
        s = _strip_think_tags(s)
        s = _strip_leading_reasoning(s)
        s = _extract_first_json_object(s)
        data = _try_parse_json_or_python_dict(s)
        return _validate_ideas_data(data, paper_ids), None
    except Exception as e:
        last_err = e
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            data = _try_parse_json_or_python_dict(raw[start : end + 1])
            return _validate_ideas_data(data, paper_ids), None
    except Exception as e:
        last_err = e
    return None, last_err


def build_ideas_propose_prompt(
    topics_config: list[dict],
    papers_compact: list[dict[str, Any]],
    briefing: dict[str, Any] | None,
    max_ideas: int = 3,
    papers_catalog: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Propose research ideas grounded in this batch. Chinese + thinking, JSON only."""
    topics_desc = "\n".join(
        f"- {t['id']}: {t['name']} — {t.get('description', '')}"
        for t in topics_config
    )
    cluster_hint = ""
    if briefing:
        cluster_hint = json.dumps(
            {
                "overview": briefing.get("overview", ""),
                "thinking": briefing.get("thinking", ""),
                "clusters": [
                    {
                        "title": c.get("title"),
                        "topic_ids": c.get("topic_ids"),
                        "narrative": c.get("narrative"),
                        "trends": c.get("trends"),
                        "divergences": c.get("divergences"),
                        "close_reads": c.get("close_reads") or [],
                    }
                    for c in (briefing.get("clusters") or [])
                ],
            },
            ensure_ascii=False,
        )
    papers_blob = json.dumps(papers_compact, ensure_ascii=False, indent=2)
    catalog_blob = json.dumps(papers_catalog or [], ensure_ascii=False, indent=2)
    system = (
        "你是系统方向的研究员，只做 ANNS / Memory / Agent OS 的 idea exploration。"
        "先充分思考机制级缺口、失败模式、是否只是复现，再输出 JSON。"
        "少而深：宁可只给 1–2 个能做实验的 idea，也不要灌水口号。"
        "每个 idea 必须能指回本批 paper_id，并写清「不是复现因为」。"
        "拒绝过大口号（「做一个通用 Agent OS」）和纯工程拼装。"
        "最终只输出一个合法 JSON 对象，字符串用简体中文。"
    )
    user = (
        f"关注主题：\n{topics_desc}\n\n"
        f"今日脉络与精读（优先从这里挖）：\n{cluster_hint or '（无）'}\n\n"
        f"精读/高价值论文（深挖用）：\n{papers_blob}\n\n"
        f"其余论文目录（避免重复已覆盖主张）：\n{catalog_blob or '（无）'}\n\n"
        f"请提出最多 {max_ideas} 个可跟的 idea。每个必须具体到机制、实验和 4–8 周 scope。\n"
        "decision 规则（默认观察）：\n"
        "- pursue：机制级缺口清楚、能写出 2–3 个实验、和已有工作可区分、4–8 周可验证\n"
        "- watch：有苗头但过新/过挤/证据不足/还只是组合口号\n"
        "- drop：已被覆盖、scope 离谱、或只是复现/工程拼装\n\n"
        "输出 JSON：\n"
        '{"thinking": "探索判断：为什么这几个值得挖、哪些只是口号", "ideas": [{'
        '"idea_id": "英文短id", "title": "中文短标题",'
        ' "topic_ids": ["ann-retrieval-systems"],'
        ' "statement": "一句话想法", "motivation": "从哪些论文/精读来",'
        ' "gap": "现有工作没做什么，机制上还缺哪一层",'
        ' "approach_sketch": "准备改哪一层、关键不变量",'
        ' "experiments": ["实验1：假设/对照/指标", "实验2", "实验3"],'
        ' "risks": ["最可能失败的原因"],'
        ' "not_a_reimplementation": "和 paper X 的差异是…",'
        ' "search_query": "English related-work search query",'
        ' "related_papers": [{"paper_id": "...", "relation": "extends|gaps|overlaps|contradicts", "note": "..."}],'
        ' "potential": {"score": 0.0, "novelty": "incremental|moderate|high",'
        ' "impact": "...", "feasibility": "low|medium|high", "why": "..."},'
        ' "scope": {"verdict": "too_narrow|just_right|too_broad",'
        ' "horizon": "4-8 weeks|workshop|conference", "why": "..."},'
        ' "decision": "pursue|watch|drop", "decision_reason": "..."}]}'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_ideas_screen_prompt(
    ideas: list[dict[str, Any]],
    external_by_idea: dict[str, list[dict[str, Any]]],
) -> list[dict[str, str]]:
    """Re-screen ideas after attaching external related-work hits."""
    payload = []
    for idea in ideas:
        item = dict(idea)
        item["external_hits"] = external_by_idea.get(idea.get("idea_id", ""), [])
        payload.append(item)
    system = (
        "你是严格的 idea 评审。根据外部相关工作更新每个 idea 的潜力和 scope。"
        "默认观察。只有机制级缺口仍在、实验仍可做、外部工作未覆盖核心主张时才保持 pursue。"
        "若外部工作已经覆盖核心主张，应降为 watch 或 drop。"
        "口号型组合（例如「CXL + ANN」但说不清改哪一层）一律 watch 或 drop。"
        "不要删 idea，必须保留全部 idea_id。"
        "最终只输出合法 JSON，字符串用简体中文。"
    )
    user = (
        "以下是初筛 idea + 外部检索命中。请更新 gap / experiments / risks / "
        "not_a_reimplementation / potential / scope / decision / "
        "decision_reason / external_related（用 overlap 说明和本 idea 的关系）。\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "输出 JSON：{\"thinking\": \"...\", \"ideas\": [与输入相同 schema 的对象，保留全部 idea_id]}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
