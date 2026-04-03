"""
Fetch blog posts from AI company/research lab blogs via RSS feeds or HTML scraping.
Returns a unified list of blog post dicts for the pipeline.
"""

import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Default request headers
_HEADERS = {
    "User-Agent": "auto-paper-reading/1.0 (research digest bot)",
    "Accept": "application/rss+xml, application/xml, text/html",
}

# Timeout for HTTP requests (seconds)
_REQUEST_TIMEOUT = 30


def _make_id(url: str) -> str:
    """Generate a stable short ID from a URL."""
    return "blog-" + hashlib.sha256(url.encode()).hexdigest()[:12]


def _parse_date(entry: dict) -> datetime | None:
    """Extract published date from a feedparser entry."""
    for field in ("published_parsed", "updated_parsed"):
        tp = entry.get(field)
        if tp:
            try:
                return datetime(*tp[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def _clean_html(raw_html: str) -> str:
    """Strip HTML tags, collapse whitespace."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


# Pattern to strip prefixed category + date from titles like:
#   "InterpretabilityOct 29, 2025Signs of introspection..."
#   "Apr 2, 2026InterpretabilityEmotion concepts..."
_DATE_PREFIX_RE = re.compile(
    r"^(?:[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})?"       # optional date prefix
    r"(?:Alignment|Interpretability|Policy|Science|Economic Research|Societal Impacts)?"  # optional category
    r"(?:[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})?"         # optional date after category
    r"(?:Alignment|Interpretability|Policy|Science|Economic Research|Societal Impacts)?"  # optional category after date
)


def _clean_title(title: str) -> str:
    """Strip common category/date prefixes from scraped titles."""
    cleaned = _DATE_PREFIX_RE.sub("", title).strip()
    # If cleaning removed too much, keep original
    return cleaned if len(cleaned) >= 15 else title


def fetch_rss(
    source_name: str,
    feed_url: str,
    days_back: int = 3,
    max_entries: int = 20,
) -> list[dict[str, Any]]:
    """
    Fetch recent blog posts from an RSS/Atom feed.

    Returns list of dicts with keys:
      id, title, url, summary, published, source, source_type
    """
    try:
        resp = requests.get(feed_url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("RSS fetch failed for %s (%s): %s", source_name, feed_url, e)
        return []

    feed = feedparser.parse(resp.text)
    if feed.bozo and not feed.entries:
        logger.warning("RSS parse failed for %s: %s", source_name, feed.bozo_exception)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    posts: list[dict[str, Any]] = []

    for entry in feed.entries[:max_entries * 2]:  # scan more, filter by date
        pub_date = _parse_date(entry)
        if pub_date and pub_date < cutoff:
            continue

        link = entry.get("link", "")
        if not link:
            continue

        # Extract summary: prefer summary/description, fall back to content
        summary = ""
        if entry.get("summary"):
            summary = _clean_html(entry.summary)
        elif entry.get("content"):
            for c in entry.content:
                if c.get("value"):
                    summary = _clean_html(c["value"])
                    break

        # Truncate very long summaries
        if len(summary) > 2000:
            summary = summary[:2000] + "..."

        posts.append({
            "id": _make_id(link),
            "title": entry.get("title", "Untitled").strip(),
            "url": link,
            "summary": summary,
            "published": pub_date.isoformat() if pub_date else "",
            "source": source_name,
            "source_type": "blog",
        })

        if len(posts) >= max_entries:
            break

    logger.info("RSS %s: fetched %d posts (cutoff=%s)", source_name, len(posts), cutoff.date())
    return posts


def fetch_html_blog(
    source_name: str,
    index_url: str,
    article_selector: str = "article a, .post a, .blog-post a",
    days_back: int = 3,
    max_entries: int = 20,
) -> list[dict[str, Any]]:
    """
    Scrape a blog index page for post links when no RSS feed is available.
    Returns a list of blog post dicts (minimal: id, title, url, source).
    """
    try:
        resp = requests.get(index_url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("HTML fetch failed for %s (%s): %s", source_name, index_url, e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    seen_urls: set[str] = set()
    posts: list[dict[str, Any]] = []

    for link_el in soup.select(article_selector):
        href = link_el.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        # Resolve relative URLs
        if href.startswith("/"):
            from urllib.parse import urljoin
            href = urljoin(index_url, href)

        if href in seen_urls:
            continue
        seen_urls.add(href)

        title = link_el.get_text(strip=True)
        if not title or len(title) < 15:
            # Try parent element for title
            parent = link_el.find_parent(["article", "div", "li"])
            if parent:
                heading = parent.find(["h1", "h2", "h3", "h4"])
                if heading:
                    title = heading.get_text(strip=True)

        if not title or len(title) < 15:
            continue

        title = _clean_title(title)

        posts.append({
            "id": _make_id(href),
            "title": title,
            "url": href,
            "summary": "",
            "published": "",
            "source": source_name,
            "source_type": "blog",
        })

        if len(posts) >= max_entries:
            break

    logger.info("HTML scrape %s: found %d posts", source_name, len(posts))
    return posts


def fetch_all_blogs(
    blog_sources: list[dict[str, Any]],
    days_back: int = 3,
    delay_between_sources: float = 2.0,
) -> list[dict[str, Any]]:
    """
    Fetch blog posts from all configured sources.

    Each source dict should have:
      name: str
      type: "rss" | "html"
      url: str
      article_selector: str (optional, for html type)
      max_entries: int (optional, default 20)
    """
    all_posts: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for i, source in enumerate(blog_sources):
        name = source.get("name", "Unknown")
        stype = source.get("type", "rss")
        url = source.get("url", "")
        max_entries = int(source.get("max_entries", 20))

        if not url:
            logger.warning("Blog source %s has no URL, skipping", name)
            continue

        if i > 0:
            time.sleep(delay_between_sources)

        if stype == "rss":
            posts = fetch_rss(name, url, days_back=days_back, max_entries=max_entries)
        elif stype == "html":
            selector = source.get("article_selector", "article a, .post a, .blog-post a")
            posts = fetch_html_blog(
                name, url, article_selector=selector,
                days_back=days_back, max_entries=max_entries,
            )
        else:
            logger.warning("Unknown blog source type %s for %s", stype, name)
            continue

        # Deduplicate by URL across sources
        for post in posts:
            if post["url"] not in seen_urls:
                all_posts.append(post)
                seen_urls.add(post["url"])

    logger.info("Total blog posts fetched: %d from %d sources", len(all_posts), len(blog_sources))
    return all_posts
