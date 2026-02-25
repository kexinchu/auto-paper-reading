"""
Fetch first-page results from Google Scholar by keyword. Uses scholarly library.
Errors (e.g. captcha, missing browser/Geckodriver) are raised so you can see and fix them.
Returns same paper shape as arxiv_client (arxiv_id, title, authors, abstract, pdf_url, etc.).
"""

import hashlib
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

try:
    from scholarly import scholarly
except ImportError:
    scholarly = None  # type: ignore

DEFAULT_MAX_PER_QUERY = 10


def _paper_id(title: str, authors: str, year: str) -> str:
    h = hashlib.sha256(f"{title}|{authors}|{year}".encode()).hexdigest()[:14]
    return f"scholar:{h}"


class ScholarError(Exception):
    """Raised when Google Scholar request fails (e.g. captcha, missing browser)."""


def fetch_papers(
    queries: list[str],
    max_per_query: int = DEFAULT_MAX_PER_QUERY,
    max_retries: int = 1,
    delay_between_queries: float = 3.0,
) -> list[dict[str, Any]]:
    """
    Search Google Scholar for each query; take first page per query.
    Raises ScholarError (or re-raises underlying error) on captcha / driver missing / failure
    so the pipeline fails visibly and you can fix the environment.
    """
    if scholarly is None:
        raise ScholarError(
            "scholarly is not installed. Install with: pip install scholarly"
        )

    seen_ids: set[str] = set()
    all_papers: list[dict[str, Any]] = []

    for q in queries:
        for attempt in range(max_retries):
            try:
                gen = scholarly.search_pubs(q)
                count = 0
                for pub in gen:
                    if count >= max_per_query:
                        break
                    try:
                        filled = scholarly.fill(pub) if not getattr(pub, "bib", None) else pub
                        bib = getattr(filled, "bib", None) or {}
                        title = (bib.get("title") or "").strip()
                        if not title:
                            continue
                        authors_list = bib.get("author", [])
                        if isinstance(authors_list, str):
                            authors_list = [authors_list]
                        authors_str = ", ".join(authors_list) if authors_list else ""
                        year = str(bib.get("year", ""))
                        abstract = (bib.get("abstract") or "").strip() or "(No abstract)"
                        pid = _paper_id(title, authors_str, year)
                        if pid in seen_ids:
                            continue
                        seen_ids.add(pid)
                        pdf_url = ""
                        eprint = getattr(filled, "eprint", None) or bib.get("eprint")
                        if eprint:
                            pdf_url = f"https://arxiv.org/pdf/{eprint}.pdf"
                        all_papers.append({
                            "arxiv_id": pid,
                            "title": title,
                            "authors": authors_list if isinstance(authors_list, list) else [authors_str],
                            "categories": [],
                            "published": f"{year}-01-01" if year else "",
                            "abstract": abstract,
                            "pdf_url": pdf_url,
                            "source": "scholar",
                        })
                        count += 1
                    except Exception as e:
                        logger.debug("Skip one scholar result: %s", e)
                        continue
                logger.info("Scholar query %r: %d papers", q, count)
                break
            except Exception as e:
                logger.error(
                    "Google Scholar failed for query %r (attempt %s/%s): %s",
                    q, attempt + 1, max_retries, e,
                    exc_info=True,
                )
                if attempt < max_retries - 1:
                    time.sleep(delay_between_queries * (attempt + 1))
                else:
                    raise ScholarError(
                        "Google Scholar request failed. Common causes: (1) Captcha — install Chrome or Firefox + Geckodriver; "
                        "(2) Rate limit — increase delay_between_queries. Original error: %s" % e
                    ) from e
        time.sleep(delay_between_queries)

    logger.info("Scholar total papers fetched: %d", len(all_papers))
    return all_papers
