"""
Stage-4 idea exploration: propose ideas, check related papers, screen potential/scope.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from openai import OpenAI

from . import model_client
from .digest import max_relevance, primary_topic_id, rich_papers_for_prompt

logger = logging.getLogger(__name__)

_DECISION_ORDER = {"pursue": 0, "watch": 1, "drop": 2}


def paper_hits_focus(
    summary: dict[str, Any],
    focus_ids: set[str],
    threshold: float,
) -> bool:
    """True if any focus topic meets the relevance threshold."""
    for t in summary.get("topics") or []:
        if not isinstance(t, dict):
            continue
        if str(t.get("topic_id") or "") not in focus_ids:
            continue
        try:
            rel = float(t.get("relevance") or 0)
        except (TypeError, ValueError):
            rel = 0.0
        if rel >= threshold:
            return True
    return False


def filter_focus_summaries(
    summaries: list[dict[str, Any]],
    topics_config: list[dict[str, Any]],
    threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split summaries into on-focus vs off-focus (e.g. recovered old-topic papers)."""
    focus_ids = {str(t["id"]) for t in topics_config}
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for summary in summaries:
        if paper_hits_focus(summary, focus_ids, threshold):
            kept.append(summary)
        else:
            dropped.append(summary)
    return kept, dropped


def _first_takeaway(summary: dict[str, Any]) -> str:
    for item in summary.get("takeaways") or []:
        text = str(item).strip()
        if text:
            return text
    return str(summary.get("problem") or "").strip()


def select_seed_summaries(
    summaries: list[dict[str, Any]],
    briefing: dict[str, Any] | None,
    max_deep: int = 8,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deep-dive on close-reads / must-read / top-relevance; catalog the rest."""
    by_id = {str(s.get("paper_id")): s for s in summaries if s.get("paper_id")}
    ordered_ids: list[str] = []

    for cluster in (briefing or {}).get("clusters") or []:
        for item in (cluster.get("close_reads") or []) + (cluster.get("must_read") or []):
            if not isinstance(item, dict):
                continue
            pid = str(item.get("paper_id") or "")
            if pid and pid in by_id and pid not in ordered_ids:
                ordered_ids.append(pid)

    rest = sorted(
        [s for s in summaries if str(s.get("paper_id")) not in set(ordered_ids)],
        key=max_relevance,
        reverse=True,
    )
    for summary in rest:
        if len(ordered_ids) >= max_deep:
            break
        pid = str(summary.get("paper_id") or "")
        if pid:
            ordered_ids.append(pid)

    seeds = [by_id[pid] for pid in ordered_ids[:max_deep] if pid in by_id]
    seed_ids = {str(s.get("paper_id")) for s in seeds}
    catalog = [
        {
            "paper_id": str(s.get("paper_id") or ""),
            "title": str(s.get("title") or ""),
            "primary_topic": primary_topic_id(s),
            "takeaway": _first_takeaway(s),
        }
        for s in summaries
        if str(s.get("paper_id")) not in seed_ids
    ]
    return seeds, catalog


def _parse_with_retry(
    client: OpenAI,
    model_name: str,
    messages: list[dict[str, str]],
    paper_ids: list[str],
    *,
    temperature: float,
    max_tokens: int,
    timeout_s: int,
    extra_body: dict[str, Any] | None,
) -> dict[str, Any]:
    last_error: Exception | None = None
    raw = ""
    for attempt in range(3):
        try:
            if attempt == 0:
                raw = model_client.chat_completion(
                    client, model_name, messages,
                    temperature=temperature, max_tokens=max_tokens, timeout_s=timeout_s,
                    extra_body=extra_body,
                )
            elif attempt == 1:
                repair = [{
                    "role": "user",
                    "content": (
                        "只输出合法 JSON 对象，不要 markdown，不要思考过程。"
                        "上一份回复无法解析。请按原 schema 重写，保留全部 idea。\n\n"
                        + (raw[:12000] if raw else "")
                    ),
                }]
                raw = model_client.chat_completion(
                    client, model_name, repair,
                    temperature=0, max_tokens=max_tokens, timeout_s=timeout_s,
                    extra_body=extra_body,
                )
            else:
                raw = model_client.chat_completion(
                    client, model_name, messages,
                    temperature=0, max_tokens=max_tokens, timeout_s=timeout_s,
                    extra_body=extra_body,
                )
            return model_client.parse_ideas_json(raw, paper_ids)
        except ValueError as e:
            last_error = e
            recovered, _ = model_client.try_parse_ideas_aggressive(raw, paper_ids)
            if recovered is not None:
                logger.info("Idea JSON recovered via aggressive parse (attempt %d)", attempt + 1)
                return recovered
            if attempt < 2:
                logger.info("Idea parse failed (attempt %d/3), retrying: %s", attempt + 1, e)
    raise last_error or RuntimeError("Idea exploration parse failed")


def _search_external_related(
    ideas: list[dict[str, Any]],
    *,
    related_limit: int,
    related_delay_s: float,
    ss_cfg: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    from . import semantic_scholar_client

    hits: dict[str, list[dict[str, Any]]] = {}
    for i, idea in enumerate(ideas):
        query = (idea.get("search_query") or idea.get("title") or "").strip()
        idea_id = str(idea.get("idea_id") or "")
        if not query or not idea_id:
            continue
        if i > 0 and related_delay_s > 0:
            time.sleep(related_delay_s)
        found = semantic_scholar_client.search_related(
            query,
            limit=related_limit,
            api_key=ss_cfg.get("api_key"),
            user_agent=ss_cfg.get("user_agent"),
        )
        hits[idea_id] = found
        logger.info("Related-work for %s (%r): %d hits", idea_id, query[:60], len(found))
    return hits


def _merge_screened(original: dict[str, Any], screened: dict[str, Any]) -> dict[str, Any]:
    """Keep every original idea; overlay screened fields when idea_id matches."""
    by_id = {str(i.get("idea_id")): i for i in screened.get("ideas") or []}
    merged: list[dict[str, Any]] = []
    for idea in original.get("ideas") or []:
        update = by_id.get(str(idea.get("idea_id")))
        if not update:
            merged.append(idea)
            continue
        combined = dict(idea)
        for key in (
            "statement", "motivation", "gap", "approach_sketch",
            "not_a_reimplementation", "potential",
            "scope", "decision", "decision_reason", "external_related",
        ):
            if update.get(key):
                combined[key] = update[key]
        if update.get("experiments"):
            combined["experiments"] = update["experiments"]
        if update.get("risks"):
            combined["risks"] = update["risks"]
        if update.get("related_papers"):
            combined["related_papers"] = update["related_papers"]
        merged.append(combined)
    merged.sort(
        key=lambda i: (
            _DECISION_ORDER.get(i.get("decision"), 9),
            -float((i.get("potential") or {}).get("score") or 0),
        )
    )
    return {
        "thinking": screened.get("thinking") or original.get("thinking") or "",
        "ideas": merged,
    }


def run_idea_exploration(
    client: OpenAI,
    model_name: str,
    summaries: list[dict[str, Any]],
    topics_config: list[dict[str, Any]],
    briefing: dict[str, Any] | None,
    *,
    temperature: float = 0,
    max_tokens: int = 16384,
    timeout_s: int = 300,
    extra_body: dict[str, Any] | None = None,
    max_ideas: int = 3,
    related_search_enabled: bool = True,
    related_limit: int = 5,
    related_delay_s: float = 8.0,
    ss_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Propose ideas, optionally check Semantic Scholar related work, then re-screen.
    Always returns all explored ideas (pursue / watch / drop). Raises on total failure.
    """
    if not summaries:
        raise ValueError("No summaries for idea exploration")

    paper_ids = [str(s.get("paper_id") or "") for s in summaries if s.get("paper_id")]
    seeds, catalog = select_seed_summaries(summaries, briefing)
    deep = rich_papers_for_prompt(seeds)
    propose_msgs = model_client.build_ideas_propose_prompt(
        topics_config, deep, briefing, max_ideas=max_ideas,
        papers_catalog=catalog,
    )
    proposed = _parse_with_retry(
        client, model_name, propose_msgs, paper_ids,
        temperature=temperature, max_tokens=max_tokens,
        timeout_s=timeout_s, extra_body=extra_body,
    )
    proposed["ideas"] = (proposed.get("ideas") or [])[:max_ideas]
    logger.info("Idea propose: %d candidates", len(proposed["ideas"]))

    if not related_search_enabled or not proposed["ideas"]:
        proposed["ideas"].sort(
            key=lambda i: (
                _DECISION_ORDER.get(i.get("decision"), 9),
                -float((i.get("potential") or {}).get("score") or 0),
            )
        )
        return proposed

    try:
        external = _search_external_related(
            proposed["ideas"],
            related_limit=related_limit,
            related_delay_s=related_delay_s,
            ss_cfg=ss_cfg or {},
        )
    except Exception as e:
        logger.warning("Related-work search skipped: %s", e)
        return proposed

    if not any(external.values()):
        logger.info("No external related-work hits; keeping propose-stage ideas")
        return proposed

    try:
        screen_msgs = model_client.build_ideas_screen_prompt(proposed["ideas"], external)
        screened = _parse_with_retry(
            client, model_name, screen_msgs, paper_ids,
            temperature=0, max_tokens=max_tokens,
            timeout_s=timeout_s, extra_body=extra_body,
        )
        result = _merge_screened(proposed, screened)
        logger.info(
            "Idea screen done: %s",
            {d: sum(1 for i in result["ideas"] if i.get("decision") == d) for d in _DECISION_ORDER},
        )
        return result
    except Exception as e:
        logger.warning("Idea re-screen failed; keeping propose-stage ideas: %s", e)
        return proposed
