"""
Send digest emails via SMTP.
Supports both plain-text (single paper) and HTML batch digest formats.
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
"""


def _h(text: str) -> str:
    """HTML-escape a string."""
    return html.escape(str(text) if text else "")


def _paper_link(paper_id: str) -> str:
    """Return arXiv or Semantic Scholar URL for a paper_id."""
    if paper_id.startswith("semantic_scholar:"):
        ss_id = paper_id[len("semantic_scholar:"):]
        return f"https://www.semanticscholar.org/paper/{ss_id}"
    return f"https://arxiv.org/abs/{paper_id}"


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
  <div class="section-title">Problem</div>
  <p class="section-body">{_h(summary.get("problem", ""))}</p>
  <div class="section-title">Motivation</div>
  <p class="section-body">{_h(summary.get("motivation", ""))}</p>
  <div class="section-title">Key Challenges</div>
  {bullet_list(summary.get("key_challenges", []))}
  <div class="section-title">Approach</div>
  <p class="section-body">{_h(summary.get("approach", ""))}</p>
  <div class="section-title">Assumptions / Limitations</div>
  {bullet_list(summary.get("assumptions_limitations", []))}
  <div class="section-title">Evidence / Results</div>
  {bullet_list(summary.get("evidence_results", []))}
  <div class="section-title">Takeaways</div>
  {bullet_list(summary.get("takeaways", []))}
  <a class="arxiv-link" href="{link}">→ 查看原文</a>
</div>
"""


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
  {papers_html}
  <p class="footer">由 auto-paper-reading 自动生成 · {_h(date_str)}</p>
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
