"""Tests for email formatting."""

from arxiv_digest import emailer


def test_format_email_body():
    summary = {
        "paper_id": "2401.1",
        "title": "Test Paper",
        "problem": "P",
        "motivation": "M",
        "key_challenges": ["C1"],
        "approach": "A",
        "assumptions_limitations": [],
        "evidence_results": ["E1"],
        "takeaways": ["t1", "t2", "t3"],
    }
    body = emailer.format_email_body(summary, pdf_path=None, include_json=False)
    assert "Test Paper" in body
    assert "P" in body and "M" in body
    assert "t1" in body and "t2" in body
    assert "2401.1" in body
    assert "JSON" not in body
