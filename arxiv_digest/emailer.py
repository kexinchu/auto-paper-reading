"""
Send digest emails via SMTP. Plain text body with optional JSON summary.
"""

import json
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def format_email_body(
    summary: dict[str, Any],
    pdf_path: str | Path | None = None,
    include_json: bool = True,
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
) -> None:
    """Send a single plain-text email. Raises on failure."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(body, "plain", "utf-8"))

    if use_tls:
        context = ssl.create_default_context()
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
    logger.info("Email sent to %s: %s", to_addr, subject[:60])
