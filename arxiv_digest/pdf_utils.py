"""
PDF download and text extraction using PyMuPDF (fitz). Optional OCR off by default.
"""

import logging
import time
from pathlib import Path
from typing import Any
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


def extract_text_fitz(pdf_path: str | Path, use_ocr: bool = False) -> str:
    """
    Extract text from PDF using PyMuPDF. Returns concatenated page text.
    If use_ocr is True and text is empty, we could call OCR (not implemented here to keep deps minimal).
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
        out = "\n\n".join(parts)
        if not out.strip() and use_ocr:
            logger.warning("No text extracted from %s; OCR requested but not implemented", path)
        return out
    finally:
        doc.close()


def extract_text(
    pdf_path: str | Path,
    use_ocr: bool = False,
) -> str:
    """
    Best-effort text extraction. Uses PyMuPDF only. OCR is optional and off by default.
    """
    return extract_text_fitz(pdf_path, use_ocr=use_ocr)
