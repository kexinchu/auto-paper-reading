"""
PDF download and text extraction using PyMuPDF (fitz). Optional OCR off by default.
Includes smart section extraction to prioritize paper body over references.
"""

import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Optional OCR: only used if text extraction yields empty and use_ocr=True
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore


def download_pdf(
    url: str,
    save_path: str | Path,
    max_retries: int = 3,
    base_delay: float = 2.0,
    timeout_s: int = 60,
) -> Path:
    """
    Download PDF from url to save_path. Creates parent dirs. Returns path.
    Raises on final failure.
    """
    path = Path(save_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout_s, stream=True)
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info("Downloaded PDF to %s", path)
            return path
        except Exception as e:
            last_err = e
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "PDF download failed (attempt %s/%s): %s; retry in %.1fs",
                attempt + 1, max_retries, e, delay,
            )
            if attempt < max_retries - 1:
                time.sleep(delay)
    raise last_err or RuntimeError("PDF download failed")


# Regex patterns for section headers to strip (references, acknowledgements, appendix)
_STRIP_SECTION_PATTERNS = re.compile(
    r'\n\s*(?:\d+\.?\s+)?(?:References|Bibliography|Acknowledgements?|Acknowledgments?)\s*\n',
    re.IGNORECASE,
)


def extract_key_sections(text: str, max_chars: int = 120000) -> str:
    """
    Smart text extraction: remove References/Bibliography sections (usually at the end)
    to avoid wasting tokens on citations. Then truncate if still too long,
    keeping beginning (Abstract+Intro+Methods) and end (Conclusion).
    """
    if len(text) <= max_chars:
        return text

    # Step 1: Try to strip References and later sections
    match = _STRIP_SECTION_PATTERNS.search(text)
    if match:
        stripped = text[:match.start()].strip()
        logger.debug(
            "Stripped references section: %d -> %d chars", len(text), len(stripped)
        )
        text = stripped

    if len(text) <= max_chars:
        return text

    # Step 2: Still too long — keep head (70%) + tail (20%), cut middle
    # Head usually contains: Abstract, Introduction, Methodology, Experiments
    # Tail usually contains: Conclusion, Discussion
    head_chars = int(max_chars * 0.75)
    tail_chars = max_chars - head_chars

    # Try to find a Conclusion section near the end to anchor the tail
    conclusion_pattern = re.compile(
        r'\n\s*(?:\d+\.?\s+)?(?:Conclusion|Conclusions|Discussion|Summary)\s*\n',
        re.IGNORECASE,
    )
    # Search only in the last 30% of the text to avoid false positives
    search_start = max(head_chars, len(text) - len(text) // 3)
    tail_match = conclusion_pattern.search(text, search_start)
    if tail_match:
        tail_text = text[tail_match.start():][:tail_chars]
    else:
        tail_text = text[-tail_chars:]

    truncated = text[:head_chars] + "\n\n[...中间内容已省略...]\n\n" + tail_text
    logger.debug(
        "Smart truncation: %d -> %d chars (head=%d, tail=%d)",
        len(text), len(truncated), head_chars, len(tail_text),
    )
    return truncated


def extract_text_fitz(pdf_path: str | Path, use_ocr: bool = False) -> str:
    """
    Extract text from PDF using PyMuPDF. Returns concatenated page text.
    Tries "text" first; if empty, falls back to building from "dict" blocks.
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is not installed. pip install pymupdf")
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    doc = fitz.open(path)
    try:
        parts = []
        for page in doc:
            text = page.get_text("text", sort=True)
            if text and text.strip():
                parts.append(text.strip())
            elif not text or not text.strip():
                # Fallback: build from dict blocks (sometimes yields text when "text" is empty)
                try:
                    d = page.get_text("dict", sort=True)
                    for block in d.get("blocks", []):
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                t = (span.get("text") or "").strip()
                                if t:
                                    parts.append(t)
                except Exception:
                    pass
        out = "\n\n".join(parts) if parts else ""
        n = len(out.strip())
        logger.info("PDF text extracted: %s -> %d chars", path.name, n)
        if n == 0 and use_ocr:
            logger.warning("No text extracted from %s; OCR requested but not implemented", path)
        return out
    finally:
        doc.close()


def extract_text(
    pdf_path: str | Path,
    use_ocr: bool = False,
    max_chars: int = 120000,
) -> str:
    """
    Best-effort text extraction with smart section filtering.
    Removes references section and applies smart truncation to max_chars.
    """
    raw = extract_text_fitz(pdf_path, use_ocr=use_ocr)
    return extract_key_sections(raw, max_chars=max_chars)
