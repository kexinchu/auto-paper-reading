"""
Fetch papers from Semantic Scholar by keyword via REST API.
No browser or kernel required; no captcha. Same paper shape as arxiv_client for pipeline.
Handles 429 rate limit with retry and backoff.
"""

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "paperId,title,abstract,year,authors,url,openAccessPdf,citationCount"
DEFAULT_LIMIT = 10
DEFAULT_TOP_K_BY_RELEVANCE = 50
# 降低请求频率，避免 429；无 API key 时约 100 req/5min
DEFAULT_DELAY_BETWEEN_QUERIES = 8.0
DEFAULT_MAX_RETRIES_429 = 3
DEFAULT_BACKOFF_BASE_S = 60


def fetch_papers(
    queries: list[str],
    limit: int = DEFAULT_LIMIT,
    top_k_by_relevance: int | None = None,
    timeout_s: int = 30,
    delay_between_queries: float = DEFAULT_DELAY_BETWEEN_QUERIES,
    max_retries_429: int = DEFAULT_MAX_RETRIES_429,
    backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
) -> list[dict[str, Any]]:
    """
    Search Semantic Scholar for each query. API returns results in relevance order.
    If top_k_by_relevance is set: take first N by relevance, then sort by citationCount desc for processing order.
    Returns list of dicts compatible with pipeline.
    On 429: retries with exponential backoff (and optional Retry-After).
    """
    seen_ids: set[str] = set()
    all_papers: list[dict[str, Any]] = []
    # Request enough per query so we can take top_k by relevance across all queries
    fetch_limit = max(limit, top_k_by_relevance or 0, 100)

    for qi, q in enumerate(queries):
        if qi > 0:
            time.sleep(delay_between_queries)

        params = {
            "query": q,
            "limit": min(fetch_limit, 100),
            "fields": FIELDS,
        }
        data = None
        for attempt in range(max_retries_429 + 1):
            try:
                r = requests.get(BASE_URL, params=params, timeout=timeout_s)
                if r.status_code == 429:
                    wait_s = backoff_base_s * (2 ** attempt)
                    retry_after = r.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait_s = max(wait_s, int(retry_after))
                    logger.warning(
                        "Semantic Scholar 429 for %r; waiting %.0fs then retry (%s/%s)",
                        q, wait_s, attempt + 1, max_retries_429 + 1,
                    )
                    time.sleep(wait_s)
                    continue
                r.raise_for_status()
                data = r.json()
                break
            except requests.RequestException as e:
                if attempt < max_retries_429 and getattr(e, "response", None) and getattr(e.response, "status_code", None) == 429:
                    wait_s = backoff_base_s * (2 ** attempt)
                    logger.warning("Semantic Scholar 429 for %r; waiting %.0fs then retry", q, wait_s)
                    time.sleep(wait_s)
                    continue
                logger.warning("Semantic Scholar request failed for %r: %s", q, e)
                break
            except (ValueError, KeyError) as e:
                logger.warning("Semantic Scholar response parse failed for %r: %s", q, e)
                break

        if data is None:
            continue

        items = data.get("data") or []
        for item in items:
            paper_id = item.get("paperId")
            if not paper_id:
                continue
            pid = f"semantic_scholar:{paper_id}"
            if pid in seen_ids:
                continue
            seen_ids.add(pid)

            title = (item.get("title") or "").strip()
            if not title:
                continue

            authors_list = item.get("authors") or []
            if isinstance(authors_list, list):
                authors = [a.get("name") or "" for a in authors_list if isinstance(a, dict)]
            else:
                authors = []
            year = item.get("year")
            year_str = str(year) if year is not None else ""
            published = f"{year_str}-01-01" if year_str else ""

            abstract = (item.get("abstract") or "").strip() or "(No abstract)"

            pdf_url = ""
            oa = item.get("openAccessPdf")
            if isinstance(oa, dict) and oa.get("url"):
                pdf_url = (oa.get("url") or "").strip()

            citation_count = item.get("citationCount")
            if citation_count is not None and not isinstance(citation_count, int):
                try:
                    citation_count = int(citation_count)
                except (TypeError, ValueError):
                    citation_count = 0
            elif citation_count is None:
                citation_count = 0

            all_papers.append({
                "arxiv_id": pid,
                "title": title,
                "authors": authors,
                "categories": [],
                "published": published,
                "abstract": abstract,
                "pdf_url": pdf_url,
                "source": "semantic_scholar",
                "citation_count": citation_count,
            })

        logger.info("Semantic Scholar query %r: %d papers", q, len(items))

    # Top-K by relevance (API order), then sort by citation for processing order
    if top_k_by_relevance is not None and top_k_by_relevance > 0 and len(all_papers) > top_k_by_relevance:
        all_papers = all_papers[:top_k_by_relevance]
        logger.info("Semantic Scholar: took top %d by relevance", top_k_by_relevance)
    all_papers.sort(key=lambda p: p.get("citation_count") or 0, reverse=True)
    logger.info("Semantic Scholar total papers fetched: %d (ordered by citation for processing)", len(all_papers))
    return all_papers
