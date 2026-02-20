"""
Fetch daily arXiv papers per category with date filtering. Retries with exponential backoff.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

import arxiv

logger = logging.getLogger(__name__)

# Base URL for PDFs
ARXIV_ABS_BASE = "https://arxiv.org/abs/"
ARXIV_PDF_BASE = "https://arxiv.org/pdf/"


def _parse_arxiv_id(entry_id: str) -> str:
    # e.g. http://arxiv.org/abs/2401.12345 -> 2401.12345
    return entry_id.rstrip("/").split("/")[-1].replace(".pdf", "")


def fetch_papers(
    categories: list[str],
    max_results_per_category: int,
    days_back: int = 1,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> list[dict[str, Any]]:
    """
    Fetch papers from arXiv for each category, filtered by published date within days_back.
    Returns list of dicts: arxiv_id, title, authors, categories, published, updated, abstract, pdf_url.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    seen_ids: set[str] = set()
    all_papers: list[dict[str, Any]] = []

    for cat in categories:
        query = f"cat:{cat}"
        before = len(all_papers)
        for attempt in range(max_retries):
            try:
                client = arxiv.Client()
                search = arxiv.Search(
                    query=query,
                    sort_by=arxiv.SortCriterion.SubmittedDate,
                    sort_order=arxiv.SortOrder.Descending,
                    max_results=max_results_per_category,
                )
                for result in client.results(search):
                    aid = _parse_arxiv_id(result.entry_id)
                    if aid in seen_ids:
                        continue
                    pub = result.published
                    if pub and pub.replace(tzinfo=timezone.utc) < cutoff:
                        continue
                    seen_ids.add(aid)
                    cat_list = [c for c in result.categories]
                    all_papers.append({
                        "arxiv_id": aid,
                        "title": result.title or "",
                        "authors": [a.name for a in result.authors],
                        "categories": cat_list,
                        "published": (result.published or result.updated).isoformat() if result.published else "",
                        "updated": result.updated.isoformat() if result.updated else "",
                        "abstract": result.summary or "",
                        "pdf_url": result.pdf_url or (ARXIV_PDF_BASE + aid + ".pdf"),
                    })
                logger.info("Fetched category %s: %d papers", cat, len(all_papers) - before)
                break
            except Exception as e:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "arXiv fetch failed for %s (attempt %s/%s): %s; retry in %.1fs",
                    cat, attempt + 1, max_retries, e, delay,
                )
                if attempt == max_retries - 1:
                    raise
                time.sleep(delay)

    # Deduplicate by arxiv_id (in case same paper in multiple categories)
    by_id: dict[str, dict[str, Any]] = {}
    for p in all_papers:
        aid = p["arxiv_id"]
        if aid not in by_id:
            by_id[aid] = p
        else:
            by_id[aid]["categories"] = list(set(by_id[aid]["categories"] + p["categories"]))

    out = list(by_id.values())
    logger.info("Total unique papers fetched: %d", len(out))
    return out
