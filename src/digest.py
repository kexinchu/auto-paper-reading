"""
Stage-3 topic briefing: cluster related topics and synthesize one Chinese digest.
"""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from . import model_client

logger = logging.getLogger(__name__)


def primary_topic_id(summary: dict[str, Any]) -> str | None:
    """Return the topic_id with the highest relevance, or None."""
    topics = summary.get("topics") or []
    best = max(
        (t for t in topics if isinstance(t, dict) and t.get("relevance", 0) > 0),
        key=lambda t: t.get("relevance", 0),
        default=None,
    )
    return best.get("topic_id") if best else None


def max_relevance(summary: dict[str, Any]) -> float:
    topics = summary.get("topics") or []
    return max(
        (t.get("relevance", 0) for t in topics if isinstance(t, dict)),
        default=0.0,
    )


def _clip(text: Any, n: int) -> str:
    s = str(text or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _topic_scores(summary: dict[str, Any], min_rel: float = 0.5) -> list[dict[str, Any]]:
    topics: list[dict[str, Any]] = []
    for t in summary.get("topics") or []:
        if not isinstance(t, dict):
            continue
        try:
            rel = float(t.get("relevance", 0))
        except (TypeError, ValueError):
            rel = 0.0
        if rel < min_rel:
            continue
        topics.append({
            "topic_id": str(t.get("topic_id") or ""),
            "relevance": round(rel, 2),
        })
    return topics


def compact_paper_for_prompt(summary: dict[str, Any], max_chars: int = 180) -> dict[str, Any]:
    """Short card kept for tests / fallback listings."""
    takeaways = [str(x) for x in (summary.get("takeaways") or [])[:3] if str(x).strip()]
    return {
        "paper_id": str(summary.get("paper_id") or ""),
        "title": str(summary.get("title") or ""),
        "published": str(summary.get("published") or "")[:10],
        "primary_topic": primary_topic_id(summary),
        "topics": _topic_scores(summary),
        "problem": _clip(summary.get("problem"), max_chars),
        "approach": _clip(summary.get("approach"), max_chars),
        "takeaways": takeaways,
    }


def rich_paper_for_prompt(summary: dict[str, Any], max_chars: int = 420) -> dict[str, Any]:
    """Stage-2 card with enough mechanism/limitation text for deep briefing and ideas."""
    def bullets(key: str, n: int = 3) -> list[str]:
        return [_clip(x, max_chars) for x in (summary.get(key) or [])[:n] if str(x).strip()]

    return {
        "paper_id": str(summary.get("paper_id") or ""),
        "title": str(summary.get("title") or ""),
        "published": str(summary.get("published") or "")[:10],
        "primary_topic": primary_topic_id(summary),
        "topics": _topic_scores(summary),
        "problem": _clip(summary.get("problem"), max_chars),
        "motivation": _clip(summary.get("motivation"), max_chars),
        "approach": _clip(summary.get("approach"), max_chars),
        "key_challenges": bullets("key_challenges"),
        "assumptions_limitations": bullets("assumptions_limitations"),
        "evidence_results": bullets("evidence_results"),
        "takeaways": bullets("takeaways"),
    }


def compact_papers_for_prompt(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compact all papers; shorten fields when the batch is large."""
    ordered = sorted(summaries, key=max_relevance, reverse=True)
    max_chars = 80 if len(ordered) > 40 else 180
    return [compact_paper_for_prompt(s, max_chars=max_chars) for s in ordered]


def rich_papers_for_prompt(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Richer cards for Stage-3/4. Slightly shorter when the batch is large."""
    ordered = sorted(summaries, key=max_relevance, reverse=True)
    max_chars = 280 if len(ordered) > 20 else 420
    return [rich_paper_for_prompt(s, max_chars=max_chars) for s in ordered]


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    s = str(value).strip()
    return [s] if s else []


def _one_liner_from_summary(summary: dict[str, Any]) -> str:
    takeaways = summary.get("takeaways") or []
    for item in takeaways:
        text = str(item).strip()
        if text:
            return text
    problem = str(summary.get("problem") or "").strip()
    return problem or "（无要点）"


def ensure_all_papers_placed(
    briefing: dict[str, Any],
    summaries: list[dict[str, Any]],
    topics_config: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach any paper the model omitted so the email never silently drops items."""
    del topics_config  # reserved for future topic-name lookup
    placed: set[str] = set()
    for cluster in briefing.get("clusters") or []:
        for paper in cluster.get("papers") or []:
            pid = paper.get("paper_id")
            if pid:
                placed.add(str(pid))

    by_id = {str(s.get("paper_id")): s for s in summaries if s.get("paper_id")}
    missing = [s for pid, s in by_id.items() if pid not in placed]
    if not missing:
        return briefing

    topic_to_cluster: dict[str, dict[str, Any]] = {}
    for cluster in briefing.get("clusters") or []:
        for tid in cluster.get("topic_ids") or []:
            topic_to_cluster.setdefault(str(tid), cluster)

    leftover: list[dict[str, str]] = []
    for summary in missing:
        pid = str(summary.get("paper_id"))
        item = {"paper_id": pid, "one_liner": _one_liner_from_summary(summary)}
        prim = primary_topic_id(summary)
        if prim and prim in topic_to_cluster:
            topic_to_cluster[prim].setdefault("papers", []).append(item)
        else:
            leftover.append(item)

    if leftover:
        briefing.setdefault("clusters", []).append({
            "cluster_id": "other",
            "title": "其他相关论文",
            "topic_ids": [],
            "why_grouped": "未能归入上述线索，单独列出以免遗漏。",
            "narrative": "",
            "trends": [],
            "divergences": [],
            "must_read": [],
            "close_reads": [],
            "papers": leftover,
        })
    return briefing


def fallback_digest(
    summaries: list[dict[str, Any]],
    topics_config: list[dict[str, Any]],
) -> dict[str, Any]:
    """Group by primary topic when Stage-3 synthesis fails."""
    topic_order = [t["id"] for t in topics_config]
    topic_names = {t["id"]: t["name"] for t in topics_config}
    groups: dict[str, list[dict[str, Any]]] = {tid: [] for tid in topic_order}
    groups["__other__"] = []

    for summary in summaries:
        prim = primary_topic_id(summary)
        bucket = prim if prim in groups else "__other__"
        groups[bucket].append(summary)

    clusters: list[dict[str, Any]] = []
    for tid in topic_order + ["__other__"]:
        papers = groups.get(tid) or []
        if not papers:
            continue
        papers.sort(key=max_relevance, reverse=True)
        title = topic_names.get(tid, "其他")
        close_reads = []
        for s in papers[:2]:
            close_reads.append({
                "paper_id": str(s.get("paper_id") or ""),
                "mechanism": _clip(s.get("approach"), 240),
                "limitation": _one_liner_from_summary(s),
                "open_question": "",
                "why_first": "回退分组中的高相关论文",
            })
        clusters.append({
            "cluster_id": tid,
            "title": title,
            "topic_ids": [] if tid == "__other__" else [tid],
            "why_grouped": "",
            "narrative": "",
            "trends": [],
            "divergences": [],
            "must_read": [],
            "close_reads": close_reads,
            "papers": [
                {
                    "paper_id": str(s.get("paper_id") or ""),
                    "one_liner": _one_liner_from_summary(s),
                }
                for s in papers
            ],
        })

    n = len(summaries)
    return {
        "overview": f"本批共 {n} 篇相关论文，按预设主题分组列出（交叉综述未能生成，已回退）。",
        "thinking": "",
        "clusters": clusters,
        "fallback": True,
    }


def run_stage3_digest(
    client: OpenAI,
    model_name: str,
    summaries: list[dict[str, Any]],
    topics_config: list[dict[str, Any]],
    *,
    temperature: float = 0,
    max_tokens: int = 16384,
    timeout_s: int = 300,
    extra_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Cluster related topics and synthesize a Chinese briefing.
    Raises on unrecoverable parse/API failure; caller should fall back.
    """
    if not summaries:
        raise ValueError("No summaries for Stage-3 digest")

    paper_ids = [str(s.get("paper_id") or "") for s in summaries if s.get("paper_id")]
    cards = rich_papers_for_prompt(summaries)
    messages = model_client.build_stage3_digest_prompt(topics_config, cards)

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
                        "上一份回复无法解析。请按原 schema 重写。\n\n"
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

            briefing = model_client.parse_stage3_digest_json(raw, paper_ids)
            briefing = ensure_all_papers_placed(briefing, summaries, topics_config)
            logger.info(
                "Stage3 digest ready: %d clusters, %d papers",
                len(briefing.get("clusters") or []),
                len(paper_ids),
            )
            return briefing
        except ValueError as e:
            last_error = e
            recovered, _ = model_client.try_parse_stage3_aggressive(raw, paper_ids)
            if recovered is not None:
                recovered = ensure_all_papers_placed(recovered, summaries, topics_config)
                logger.info("Stage3 recovered via aggressive parse (attempt %d)", attempt + 1)
                return recovered
            if attempt < 2:
                logger.info("Stage3 parse failed (attempt %d/3), retrying: %s", attempt + 1, e)

    raise last_error or RuntimeError("Stage3 digest failed")
