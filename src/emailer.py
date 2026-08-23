"""
Send digest emails via SMTP.
Supports topic-briefing HTML (default), per-paper HTML, and plain-text fallback.
"""

import html
import json
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# HTML digest (batch, all papers in one email)
# ──────────────────────────────────────────────────────────────────────────────

_HTML_STYLE = """
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
  max-width: 860px; margin: 0 auto; padding: 24px; color: #2d2d2d; line-height: 1.6;
  background: #fafafa;
}
h1 { color: #1a1a2e; border-bottom: 3px solid #3498db; padding-bottom: 12px; margin-bottom: 8px; }
.stats { color: #555; font-size: 0.92em; margin-bottom: 20px; }
.toc {
  background: #eef6ff; border: 1px solid #bee3f8; border-radius: 8px;
  padding: 16px 22px; margin: 20px 0;
}
.toc h2 { margin: 0 0 10px; font-size: 1em; color: #2980b9; }
.toc ol { margin: 0; padding-left: 22px; }
.toc li { margin: 5px 0; font-size: 0.95em; }
.toc a { color: #2980b9; text-decoration: none; }
.toc a:hover { text-decoration: underline; }
.topic-section { margin: 36px 0 8px; }
.topic-section-header {
  background: linear-gradient(90deg, #2980b9 0%, #3498db 100%);
  color: #fff; border-radius: 8px 8px 0 0;
  padding: 10px 20px; font-size: 1.05em; font-weight: 700;
  display: flex; justify-content: space-between; align-items: center;
}
.topic-section-count {
  background: rgba(255,255,255,0.25); border-radius: 12px;
  padding: 1px 10px; font-size: 0.85em; font-weight: 600;
}
.paper { background: #fff; border: 1px solid #e0e0e0; border-radius: 10px; padding: 22px 28px; margin: 28px 0; }
.paper h2 { color: #1a1a2e; margin-top: 0; font-size: 1.15em; }
.paper-meta { font-size: 0.88em; color: #666; background: #f5f5f5; border-radius: 6px;
  padding: 8px 12px; margin: 10px 0 14px; }
.paper-meta a { color: #2980b9; }
.topic-tags { margin: 8px 0 16px; }
.topic-tag {
  display: inline-block; background: #e8f4f8; color: #1a6b9a;
  border-radius: 4px; padding: 2px 9px; margin: 2px 3px 2px 0;
  font-size: 0.82em; border: 1px solid #bee3f8;
}
.section-title {
  font-size: 0.82em; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.07em; color: #888; margin: 18px 0 6px;
}
.section-body { margin: 0 0 4px; }
ul.bullet { margin: 4px 0; padding-left: 22px; }
ul.bullet li { margin: 4px 0; }
.arxiv-link {
  display: inline-block; margin-top: 14px; color: #2980b9;
  font-size: 0.9em; font-weight: 600; text-decoration: none;
}
.arxiv-link:hover { text-decoration: underline; }
hr { border: none; border-top: 1px solid #ececec; margin: 8px 0; }
.footer { color: #aaa; font-size: 0.82em; margin-top: 30px; text-align: center; }
.thinking-box {
  background: #fff8e7; border: 1px solid #f0d78c; border-left: 4px solid #e67e22;
  border-radius: 8px; padding: 16px 20px; margin: 18px 0 24px;
}
.thinking-box h2 { margin: 0 0 8px; font-size: 1em; color: #c0392b; }
.thinking-box .overview { margin: 0 0 10px; }
.thinking-box .thinking { margin: 0; color: #5d4e37; }
.cluster-why { margin: 10px 20px 0; color: #666; font-size: 0.9em; }
.narrative { margin: 12px 20px 8px; font-size: 0.98em; }
.cluster-lists { margin: 8px 20px 16px; }
.must-read {
  background: #fff4e5; border: 1px solid #f5c16c; border-radius: 8px;
  padding: 10px 16px; margin: 10px 20px 16px;
}
.must-read h3 { margin: 0 0 6px; font-size: 0.92em; color: #b9770e; }
.close-read {
  background: #f4faf6; border: 1px solid #b7e0c4; border-left: 4px solid #1e8449;
  border-radius: 8px; padding: 12px 16px; margin: 10px 20px 14px;
}
.close-read h3 { margin: 0 0 8px; font-size: 0.95em; color: #145a32; }
.paper-compact {
  background: #fff; border: 1px solid #e0e0e0; border-radius: 8px;
  padding: 12px 16px; margin: 10px 0;
}
.paper-compact h3 { color: #1a1a2e; margin: 0 0 6px; font-size: 1em; }
.paper-compact .one-liner { margin: 0 0 8px; }
.paper-compact .arxiv-link { margin-top: 4px; }
.idea-card {
  background: #fff; border: 1px solid #e0e0e0; border-radius: 10px;
  padding: 16px 20px; margin: 14px 0;
}
.idea-card h3 { margin: 0 0 8px; font-size: 1.05em; color: #1a1a2e; }
.idea-badge {
  display: inline-block; border-radius: 12px; padding: 1px 10px;
  font-size: 0.78em; font-weight: 700; margin-right: 8px; color: #fff;
}
.idea-badge.pursue { background: #1e8449; }
.idea-badge.watch { background: #b9770e; }
.idea-badge.drop { background: #7f8c8d; }
.idea-meta { font-size: 0.88em; color: #555; margin: 6px 0 10px; }
.idea-card.drop { opacity: 0.88; }
"""


def _h(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text) if text else "")


def _paper_link(paper_id: str) -> str:
    """Return arXiv PDF or Semantic Scholar URL for a paper_id."""
    if paper_id.startswith("semantic_scholar:"):
        ss_id = paper_id[len("semantic_scholar:"):]
        return f"https://www.semanticscholar.org/paper/{ss_id}"
    return f"https://arxiv.org/pdf/{paper_id}"


def _build_paper_html(idx: int, summary: dict[str, Any]) -> str:
    paper_id = summary.get("paper_id", "")
    title = summary.get("title", "(No title)")
    published = summary.get("published", "")
    categories = summary.get("categories", [])
    if isinstance(categories, list):
        cats_str = ", ".join(categories)
    else:
        cats_str = str(categories)

    # Topic tags with relevance
    topics = summary.get("topics", [])
    relevant_topics = sorted(
        [t for t in topics if isinstance(t, dict) and t.get("relevance", 0) >= 0.5],
        key=lambda t: t.get("relevance", 0),
        reverse=True,
    )
    tags_html = "".join(
        f'<span class="topic-tag">{_h(t.get("topic_id", ""))}'
        f' <b>{t.get("relevance", 0):.1f}</b></span>'
        for t in relevant_topics
    )

    def bullet_list(items: list) -> str:
        if not items:
            return "<p class='section-body'><em>not reported</em></p>"
        lis = "".join(f"<li>{_h(item)}</li>" for item in items)
        return f"<ul class='bullet'>{lis}</ul>"

    link = _paper_link(paper_id)
    return f"""
<div class="paper" id="p{idx}">
  <h2>{idx}. {_h(title)}</h2>
  <div class="paper-meta">
    <b>ID:</b> <a href="{link}">{_h(paper_id)}</a> &nbsp;|&nbsp;
    <b>Published:</b> {_h(published)} &nbsp;|&nbsp;
    <b>Categories:</b> {_h(cats_str)}
  </div>
  <div class="topic-tags">{tags_html if tags_html else "<em>No matched topics</em>"}</div>
  <hr>
  <div class="section-title">问题</div>
  <p class="section-body">{_h(summary.get("problem", ""))}</p>
  <div class="section-title">动机</div>
  <p class="section-body">{_h(summary.get("motivation", ""))}</p>
  <div class="section-title">关键挑战</div>
  {bullet_list(summary.get("key_challenges", []))}
  <div class="section-title">方法</div>
  <p class="section-body">{_h(summary.get("approach", ""))}</p>
  <div class="section-title">假设与局限</div>
  {bullet_list(summary.get("assumptions_limitations", []))}
  <div class="section-title">实验结果</div>
  {bullet_list(summary.get("evidence_results", []))}
  <div class="section-title">要点总结</div>
  {bullet_list(summary.get("takeaways", []))}
  <a class="arxiv-link" href="{link}">→ 查看原文</a>
</div>
"""


def _build_blog_post_html(idx: int, post: dict[str, Any]) -> str:
    """Build HTML card for a single blog post."""
    title = post.get("title", "(Untitled)")
    url = post.get("url", "")
    source = post.get("source", "")
    published = post.get("published", "")
    summary = post.get("summary", "")

    # Truncate summary for email display
    if len(summary) > 500:
        summary = summary[:500] + "..."

    return f"""
<div class="paper" id="blog{idx}">
  <h2>{idx}. {_h(title)}</h2>
  <div class="paper-meta">
    <b>Source:</b> {_h(source)} &nbsp;|&nbsp;
    <b>Published:</b> {_h(published[:10] if published else "")} &nbsp;|&nbsp;
    <a href="{_h(url)}" style="color:#2980b9;font-weight:600">Read Full Post</a>
  </div>
  <hr>
  <p class="section-body">{_h(summary) if summary else "<em>No summary available — click to read</em>"}</p>
  <a class="arxiv-link" href="{_h(url)}">→ Read Full Post</a>
</div>
"""


def _build_blog_section_html(blog_posts: list[dict[str, Any]]) -> str:
    """Build the Blog & Community section for the digest."""
    if not blog_posts:
        return ""

    # Group by source
    by_source: dict[str, list[dict]] = {}
    for post in blog_posts:
        src = post.get("source", "Other")
        by_source.setdefault(src, []).append(post)

    parts = [
        '<div class="topic-section" id="topic-blogs">',
        '<div class="topic-section-header" style="background:linear-gradient(90deg,#8e44ad 0%,#9b59b6 100%)">',
        f'Blog & Community Updates',
        f'<span class="topic-section-count">{len(blog_posts)} posts</span>',
        '</div></div>',
    ]

    global_idx = 1
    for source_name, posts in by_source.items():
        parts.append(
            f'<div style="margin:18px 0 8px;padding:6px 14px;background:#f3e8ff;'
            f'border-left:4px solid #8e44ad;border-radius:4px;font-weight:600;color:#6b21a8">'
            f'{_h(source_name)} ({len(posts)})</div>'
        )
        for post in posts:
            parts.append(_build_blog_post_html(global_idx, post))
            global_idx += 1

    return "\n".join(parts)


def _get_primary_topic(summary: dict[str, Any]) -> str | None:
    """Return the topic_id with the highest relevance score, or None."""
    topics = summary.get("topics") or []
    best = max(
        (t for t in topics if isinstance(t, dict) and t.get("relevance", 0) > 0),
        key=lambda t: t.get("relevance", 0),
        default=None,
    )
    return best["topic_id"] if best else None


def _max_relevance(summary: dict[str, Any]) -> float:
    topics = summary.get("topics") or []
    return max((t.get("relevance", 0) for t in topics if isinstance(t, dict)), default=0.0)


def format_html_digest(
    summaries: list[dict[str, Any]],
    date_str: str,
    stats: dict[str, Any] | None = None,
    topics_config: list[dict[str, Any]] | None = None,
    blog_posts: list[dict[str, Any]] | None = None,
) -> str:
    """
    Build a complete HTML digest email for multiple papers.

    When topics_config is provided, papers are grouped by their primary topic
    (highest relevance) and shown in topic sections. Otherwise, sorted by relevance.
    """
    n = len(summaries)
    stats_line = ""
    if stats:
        total = stats.get("total", "?")
        kw_skipped = stats.get("skipped_keyword", 0)
        stage2_ok = stats.get("stage2_ok", n)
        failed = stats.get("stage2_failed", 0) + stats.get("stage1_failed", 0)
        abstract_only = stats.get("abstract_only", 0)
        parts = [f"共 <b>{total}</b> 篇候选 → <b>{n}</b> 篇相关"]
        if kw_skipped:
            parts.append(f"关键词预过滤 {kw_skipped} 篇")
        if abstract_only:
            parts.append(f"摘要直通 {abstract_only} 篇")
        if failed:
            parts.append(f"失败 {failed} 篇")
        stats_line = " | ".join(parts)

    if topics_config:
        # Group by primary topic, in topics_config order
        topic_order = [t["id"] for t in topics_config]
        topic_names = {t["id"]: t["name"] for t in topics_config}
        groups: dict[str, list[dict]] = {tid: [] for tid in topic_order}
        groups["__other__"] = []

        for s in summaries:
            primary = _get_primary_topic(s)
            bucket = primary if primary in groups else "__other__"
            groups[bucket].append(s)

        # Sort within each group by relevance
        for bucket in groups:
            groups[bucket].sort(key=_max_relevance, reverse=True)

        # Build TOC (topic-level)
        toc_items = []
        for tid in topic_order:
            group = groups.get(tid, [])
            if group:
                toc_items.append(
                    f'<li><a href="#topic-{_h(tid)}">'
                    f'{_h(topic_names.get(tid, tid))} '
                    f'<span style="color:#888">({len(group)})</span></a>'
                    "<ul>"
                    + "".join(
                        f'<li><a href="#p{s.get("_idx", "")}">· {_h(s.get("title", ""))}</a></li>'
                        for s in group
                    )
                    + "</ul></li>"
                )
        toc_html = f'<div class="toc"><h2>目录 ({n} 篇)</h2><ol>{"".join(toc_items)}</ol></div>'

        # Assign global indices and build body sections
        global_idx = 1
        body_parts = []
        for tid in topic_order:
            group = groups.get(tid, [])
            if not group:
                continue
            body_parts.append(
                f'<div class="topic-section" id="topic-{_h(tid)}">'
                f'<div class="topic-section-header">'
                f'{_h(topic_names.get(tid, tid))}'
                f'<span class="topic-section-count">{len(group)} 篇</span>'
                f'</div></div>'
            )
            for s in group:
                s["_idx"] = global_idx
                body_parts.append(_build_paper_html(global_idx, s))
                global_idx += 1
        papers_html = "\n".join(body_parts)

    else:
        # Flat list sorted by relevance
        ordered = sorted(summaries, key=_max_relevance, reverse=True)
        toc_items_flat = "\n".join(
            f'<li><a href="#p{i + 1}">{_h(s.get("title", "(No title)"))}</a></li>'
            for i, s in enumerate(ordered)
        )
        toc_html = (
            f'<div class="toc"><h2>目录 ({n} 篇)</h2><ol>{toc_items_flat}</ol></div>'
            if ordered else ""
        )
        papers_html = "\n".join(_build_paper_html(i + 1, s) for i, s in enumerate(ordered))

    # Blog section
    blog_html = _build_blog_section_html(blog_posts or [])
    blog_toc = ""
    if blog_posts:
        blog_toc = (
            f'<div style="margin-top:12px;padding-top:8px;border-top:1px solid #ddd">'
            f'<a href="#topic-blogs" style="color:#8e44ad;font-weight:600">'
            f'Blog & Community ({len(blog_posts)} posts)</a></div>'
        )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>arXiv Digest — {_h(date_str)}</title>
  <style>{_HTML_STYLE}</style>
</head>
<body>
  <h1>arXiv Digest — {_h(date_str)}</h1>
  <p class="stats">{stats_line}</p>
  {toc_html}
  {blog_toc}
  {papers_html}
  {blog_html}
  <p class="footer">由 auto-paper-reading 自动生成 · {_h(date_str)}</p>
</body>
</html>"""


def _stats_line(stats: dict[str, Any] | None, n: int) -> str:
    if not stats:
        return ""
    total = stats.get("total", "?")
    kw_skipped = stats.get("skipped_keyword", 0)
    failed = stats.get("stage2_failed", 0) + stats.get("stage1_failed", 0)
    abstract_only = stats.get("abstract_only", 0)
    parts = [f"共 <b>{total}</b> 篇候选 → <b>{n}</b> 篇相关"]
    if kw_skipped:
        parts.append(f"关键词预过滤 {kw_skipped} 篇")
    if abstract_only:
        parts.append(f"摘要直通 {abstract_only} 篇")
    if failed:
        parts.append(f"失败 {failed} 篇")
    off_focus = stats.get("skipped_off_focus", 0)
    if off_focus:
        parts.append(f"非焦点主题 {off_focus} 篇")
    n_ideas = stats.get("ideas_explored", 0)
    if n_ideas:
        parts.append(f"探索想法 {n_ideas} 个")
    return " | ".join(parts)


def _compact_paper_html(
    idx: int,
    paper_ref: dict[str, Any],
    summary: dict[str, Any] | None,
) -> str:
    """One-line paper card used in the topic briefing."""
    paper_id = paper_ref.get("paper_id") or (summary or {}).get("paper_id") or ""
    title = (summary or {}).get("title") or paper_id or "(No title)"
    published = str((summary or {}).get("published") or "")[:10]
    one_liner = (paper_ref.get("one_liner") or "").strip()
    if not one_liner and summary:
        takeaways = summary.get("takeaways") or []
        one_liner = str(takeaways[0]).strip() if takeaways else ""
    if not one_liner:
        one_liner = "（无要点）"

    topics = (summary or {}).get("topics") or []
    relevant_topics = sorted(
        [t for t in topics if isinstance(t, dict) and t.get("relevance", 0) >= 0.5],
        key=lambda t: t.get("relevance", 0),
        reverse=True,
    )
    tags_html = "".join(
        f'<span class="topic-tag">{_h(t.get("topic_id", ""))}'
        f' <b>{t.get("relevance", 0):.1f}</b></span>'
        for t in relevant_topics
    )
    link = _paper_link(str(paper_id))
    return f"""
<div class="paper-compact" id="p{idx}">
  <h3>{idx}. {_h(title)}</h3>
  <p class="one-liner">{_h(one_liner)}</p>
  <div class="paper-meta">
    <b>ID:</b> <a href="{link}">{_h(paper_id)}</a>
    {f' &nbsp;|&nbsp; <b>Published:</b> {_h(published)}' if published else ''}
  </div>
  <div class="topic-tags">{tags_html}</div>
  <a class="arxiv-link" href="{link}">→ 查看原文</a>
</div>
"""


_DECISION_LABEL = {"pursue": "值得跟", "watch": "观察", "drop": "放下"}
_SCOPE_LABEL = {
    "too_narrow": "过窄",
    "just_right": "合适",
    "too_broad": "过大",
}
_RELATION_LABEL = {
    "extends": "延伸",
    "gaps": "缺口",
    "overlaps": "重叠",
    "contradicts": "对照",
}


def _idea_card_html(
    idea: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
) -> str:
    decision = str(idea.get("decision") or "watch")
    badge = _DECISION_LABEL.get(decision, decision)
    potential = idea.get("potential") or {}
    scope = idea.get("scope") or {}
    score = potential.get("score")
    try:
        score_txt = f"{float(score):.2f}"
    except (TypeError, ValueError):
        score_txt = "—"
    horizon = scope.get("horizon") or ""
    horizon_html = f" · {_h(horizon)}" if horizon else ""
    scope_txt = _SCOPE_LABEL.get(scope.get("verdict"), scope.get("verdict") or "—")
    tags = "".join(
        f'<span class="topic-tag">{_h(tid)}</span>'
        for tid in (idea.get("topic_ids") or [])
    )
    related_lis = []
    for rel in idea.get("related_papers") or []:
        pid = rel.get("paper_id", "")
        title = (by_id.get(pid) or {}).get("title") or pid
        rel_l = _RELATION_LABEL.get(rel.get("relation", ""), rel.get("relation", ""))
        note = rel.get("note") or ""
        related_lis.append(
            f"<li><b>{_h(rel_l)}</b> {_h(title)}"
            f"{f' — {_h(note)}' if note else ''}</li>"
        )
    external_lis = []
    for ext in idea.get("external_related") or []:
        title = ext.get("title") or ""
        year = ext.get("year") or ""
        url = ext.get("url") or ""
        overlap = ext.get("overlap") or ""
        head = f'<a href="{_h(url)}">{_h(title)}</a>' if url else _h(title)
        if year:
            head += f" ({_h(year)})"
        external_lis.append(f"<li>{head}{f' — {_h(overlap)}' if overlap else ''}</li>")

    bits = [
        f'<div class="idea-card { _h(decision) }">',
        f'<h3><span class="idea-badge { _h(decision) }">{_h(badge)}</span>{_h(idea.get("title") or "")}</h3>',
        f'<div class="idea-meta">潜力 {_h(score_txt)} · '
        f'新颖度 {_h(potential.get("novelty") or "—")} · '
        f'可行性 {_h(potential.get("feasibility") or "—")} · '
        f'scope {_h(scope_txt)}{horizon_html}</div>',
        f'<div class="topic-tags">{tags}</div>' if tags else "",
    ]
    if idea.get("statement"):
        bits.append(f'<p>{_h(idea["statement"])}</p>')
    if idea.get("motivation"):
        bits.append(f'<div class="section-title">来源 / 缺口</div><p class="section-body">{_h(idea["motivation"])}</p>')
    if idea.get("gap"):
        bits.append(f'<div class="section-title">机制缺口</div><p class="section-body">{_h(idea["gap"])}</p>')
    if idea.get("approach_sketch"):
        bits.append(f'<div class="section-title">做法草图</div><p class="section-body">{_h(idea["approach_sketch"])}</p>')
    if idea.get("experiments"):
        items = "".join(f"<li>{_h(x)}</li>" for x in idea["experiments"])
        bits.append(f'<div class="section-title">可做实验</div><ul class="bullet">{items}</ul>')
    if idea.get("risks"):
        items = "".join(f"<li>{_h(x)}</li>" for x in idea["risks"])
        bits.append(f'<div class="section-title">失败风险</div><ul class="bullet">{items}</ul>')
    if idea.get("not_a_reimplementation"):
        bits.append(
            f'<div class="section-title">不是复现因为</div>'
            f'<p class="section-body">{_h(idea["not_a_reimplementation"])}</p>'
        )
    if potential.get("why"):
        bits.append(f'<div class="section-title">潜力判断</div><p class="section-body">{_h(potential["why"])}</p>')
    if scope.get("why"):
        bits.append(f'<div class="section-title">Scope</div><p class="section-body">{_h(scope["why"])}</p>')
    if idea.get("decision_reason"):
        bits.append(f'<div class="section-title">结论</div><p class="section-body">{_h(idea["decision_reason"])}</p>')
    if related_lis:
        bits.append(
            f'<div class="section-title">本批相关论文</div><ul class="bullet">{"".join(related_lis)}</ul>'
        )
    if external_lis:
        bits.append(
            f'<div class="section-title">外部相关工作</div><ul class="bullet">{"".join(external_lis)}</ul>'
        )
    bits.append("</div>")
    return "\n".join(x for x in bits if x)


def _ideas_section_html(
    idea_briefing: dict[str, Any] | None,
    by_id: dict[str, dict[str, Any]],
) -> str:
    if not idea_briefing:
        return ""
    idea_list = idea_briefing.get("ideas") or []
    if not idea_list:
        return ""
    counts = {
        "pursue": sum(1 for i in idea_list if i.get("decision") == "pursue"),
        "watch": sum(1 for i in idea_list if i.get("decision") == "watch"),
        "drop": sum(1 for i in idea_list if i.get("decision") == "drop"),
    }
    parts = [
        '<div class="topic-section" id="ideas">',
        '<div class="topic-section-header" style="background:linear-gradient(90deg,#1e8449 0%,#27ae60 100%)">',
        "想法探索",
        f'<span class="topic-section-count">{len(idea_list)} 个'
        f' · 跟 {counts["pursue"]} / 看 {counts["watch"]} / 放 {counts["drop"]}</span>',
        "</div></div>",
    ]
    thinking = (idea_briefing.get("thinking") or "").strip()
    if thinking:
        parts.append(
            f'<div class="thinking-box"><h2>探索判断</h2>'
            f'<p class="thinking">{_h(thinking)}</p></div>'
        )
    for idea in idea_list:
        parts.append(_idea_card_html(idea, by_id))
    return "\n".join(parts)


def format_topic_briefing_html(
    briefing: dict[str, Any] | None,
    summaries: list[dict[str, Any]],
    date_str: str,
    stats: dict[str, Any] | None = None,
    blog_posts: list[dict[str, Any]] | None = None,
    idea_briefing: dict[str, Any] | None = None,
) -> str:
    """
    Build a single HTML email: Chinese topic briefing, idea exploration, compact papers.
    Papers are organized by clustered research threads, not as standalone reports.
    """
    briefing = briefing or {"overview": "", "thinking": "", "clusters": []}
    by_id = {str(s.get("paper_id")): s for s in summaries if s.get("paper_id")}
    n = len(summaries)
    clusters = briefing.get("clusters") or []
    stats_line = _stats_line(stats, n)

    thinking_html = ""
    overview = (briefing.get("overview") or "").strip()
    thinking = (briefing.get("thinking") or "").strip()
    if overview or thinking:
        parts = ['<div class="thinking-box"><h2>今日判断</h2>']
        if overview:
            parts.append(f'<p class="overview">{_h(overview)}</p>')
        if thinking:
            parts.append(f'<p class="thinking">{_h(thinking)}</p>')
        parts.append("</div>")
        thinking_html = "\n".join(parts)

    toc_items = []
    for cluster in clusters:
        cid = cluster.get("cluster_id") or ""
        title = cluster.get("title") or cid
        count = len(cluster.get("papers") or [])
        toc_items.append(
            f'<li><a href="#cluster-{_h(cid)}">{_h(title)} '
            f'<span style="color:#888">({count})</span></a></li>'
        )
    toc_html = ""
    if toc_items:
        toc_html = (
            f'<div class="toc"><h2>研究线索 ({len(clusters)})</h2>'
            f'<ol>{"".join(toc_items)}</ol></div>'
        )

    body_parts: list[str] = []
    global_idx = 1
    for cluster in clusters:
        cid = cluster.get("cluster_id") or ""
        title = cluster.get("title") or cid
        papers = cluster.get("papers") or []
        body_parts.append(
            f'<div class="topic-section" id="cluster-{_h(cid)}">'
            f'<div class="topic-section-header">'
            f'{_h(title)}'
            f'<span class="topic-section-count">{len(papers)} 篇</span>'
            f'</div></div>'
        )
        if cluster.get("why_grouped"):
            body_parts.append(
                f'<p class="cluster-why">{_h(cluster["why_grouped"])}</p>'
            )
        if cluster.get("narrative"):
            body_parts.append(
                f'<p class="narrative">{_h(cluster["narrative"])}</p>'
            )

        list_bits: list[str] = []
        if cluster.get("trends"):
            items = "".join(f"<li>{_h(x)}</li>" for x in cluster["trends"])
            list_bits.append(f"<div><b>共同方向</b><ul class='bullet'>{items}</ul></div>")
        if cluster.get("divergences"):
            items = "".join(f"<li>{_h(x)}</li>" for x in cluster["divergences"])
            list_bits.append(f"<div><b>分歧 / 不同路线</b><ul class='bullet'>{items}</ul></div>")
        if list_bits:
            body_parts.append(f'<div class="cluster-lists">{"".join(list_bits)}</div>')

        must_read = cluster.get("must_read") or []
        if must_read:
            lis = []
            for item in must_read:
                pid = item.get("paper_id", "")
                why = item.get("why") or ""
                paper_title = (by_id.get(pid) or {}).get("title") or pid
                why_html = f"：{_h(why)}" if why else ""
                lis.append(f"<li><b>{_h(paper_title)}</b>{why_html}</li>")
            body_parts.append(
                f'<div class="must-read"><h3>建议先读</h3><ul class="bullet">'
                f'{"".join(lis)}</ul></div>'
            )

        close_reads = cluster.get("close_reads") or []
        if close_reads:
            for item in close_reads:
                if not isinstance(item, dict):
                    continue
                pid = str(item.get("paper_id") or "")
                paper_title = (by_id.get(pid) or {}).get("title") or pid
                bits = [f'<div class="close-read"><h3>精读 · {_h(paper_title)}</h3>']
                if item.get("why_first"):
                    bits.append(f'<p class="cluster-why" style="margin:0 0 8px">{_h(item["why_first"])}</p>')
                if item.get("mechanism"):
                    bits.append(
                        f'<div class="section-title">机制</div>'
                        f'<p class="section-body">{_h(item["mechanism"])}</p>'
                    )
                if item.get("limitation"):
                    bits.append(
                        f'<div class="section-title">局限 / 没做什么</div>'
                        f'<p class="section-body">{_h(item["limitation"])}</p>'
                    )
                if item.get("open_question"):
                    bits.append(
                        f'<div class="section-title">开放问题</div>'
                        f'<p class="section-body">{_h(item["open_question"])}</p>'
                    )
                bits.append("</div>")
                body_parts.append("\n".join(bits))

        for paper_ref in papers:
            pid = str(paper_ref.get("paper_id") or "")
            body_parts.append(_compact_paper_html(global_idx, paper_ref, by_id.get(pid)))
            global_idx += 1

    papers_html = "\n".join(body_parts)
    ideas_html = _ideas_section_html(idea_briefing, by_id)
    n_ideas = len((idea_briefing or {}).get("ideas") or [])
    blog_html = _build_blog_section_html(blog_posts or [])
    extra_toc = []
    if n_ideas:
        extra_toc.append(
            f'<div style="margin-top:12px;padding-top:8px;border-top:1px solid #ddd">'
            f'<a href="#ideas" style="color:#1e8449;font-weight:600">'
            f'想法探索 ({n_ideas})</a></div>'
        )
    if blog_posts:
        extra_toc.append(
            f'<div style="margin-top:12px;padding-top:8px;border-top:1px solid #ddd">'
            f'<a href="#topic-blogs" style="color:#8e44ad;font-weight:600">'
            f'Blog & Community ({len(blog_posts)} posts)</a></div>'
        )
    extra_toc_html = "\n".join(extra_toc)
    footer_label = "按研究线索 + 想法探索汇总" if n_ideas else "按研究线索汇总"

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>今日论文脉络 — {_h(date_str)}</title>
  <style>{_HTML_STYLE}</style>
</head>
<body>
  <h1>今日论文脉络 — {_h(date_str)}</h1>
  <p class="stats">{stats_line}</p>
  {thinking_html}
  {toc_html}
  {extra_toc_html}
  {ideas_html}
  {papers_html}
  {blog_html}
  <p class="footer">由 auto-paper-reading {footer_label} · {_h(date_str)}</p>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────────────────────
# Plain-text format (kept for backward compatibility / fallback)
# ──────────────────────────────────────────────────────────────────────────────

def format_email_body(
    summary: dict[str, Any],
    pdf_path: str | Path | None = None,
    include_json: bool = False,
) -> str:
    """Plain text body: sections + optional JSON at bottom."""
    lines = [
        f"Title: {summary.get('title', '')}",
        f"Paper ID: {summary.get('paper_id', '')}",
        f"Categories: {summary.get('categories', [])}",
        f"Published: {summary.get('published', '')}",
        "",
        "--- Problem ---",
        summary.get("problem", ""),
        "",
        "--- Motivation ---",
        summary.get("motivation", ""),
        "",
        "--- Key challenges ---",
    ]
    for c in summary.get("key_challenges", []):
        lines.append(f"  - {c}")
    lines.extend([
        "",
        "--- Approach ---",
        summary.get("approach", ""),
        "",
        "--- Assumptions / Limitations ---",
    ])
    for a in summary.get("assumptions_limitations", []):
        lines.append(f"  - {a}")
    lines.extend([
        "",
        "--- Evidence / Results ---",
    ])
    for e in summary.get("evidence_results", []):
        lines.append(f"  - {e}")
    lines.extend([
        "",
        "--- Takeaways ---",
    ])
    for t in summary.get("takeaways", []):
        lines.append(f"  - {t}")
    if pdf_path:
        lines.extend(["", "--- PDF ---", str(pdf_path)])
    if include_json:
        lines.extend(["", "--- JSON ---", json.dumps(summary, ensure_ascii=False, indent=2)])
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# SMTP sender
# ──────────────────────────────────────────────────────────────────────────────

def send_digest_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_addr: str,
    to_addr: str,
    use_tls: bool,
    subject: str,
    body: str,
    is_html: bool = False,
) -> None:
    """Send a digest email. Set is_html=True for HTML content. Raises on failure."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    content_type = "html" if is_html else "plain"
    msg.attach(MIMEText(body, content_type, "utf-8"))

    context = ssl.create_default_context()
    # 465 = implicit SSL (SMTP_SSL); 587 = explicit TLS (SMTP + STARTTLS)
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    elif use_tls:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls(context=context)
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
    logger.info("Email sent to %s: %s", to_addr, subject[:80])
