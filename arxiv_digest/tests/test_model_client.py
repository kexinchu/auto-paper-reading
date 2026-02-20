"""Tests for model_client JSON parsing and prompt building."""

import pytest

from arxiv_digest import model_client
from arxiv_digest.topics import load_topics


def test_parse_stage1_json():
    raw = '{"paper_id":"2401.1","topics":[{"topic_id":"anns","relevance":0.9,"reason":"good"}],"overall_relevance":0.85,"decision":"keep"}'
    out = model_client.parse_stage1_json(raw, "2401.1")
    assert out["paper_id"] == "2401.1"
    assert out["decision"] == "keep"
    assert out["topics"][0]["relevance"] == 0.9
    assert out["overall_relevance"] == 0.85


def test_parse_stage1_clamp_relevance():
    raw = '{"paper_id":"x","topics":[{"topic_id":"a","relevance":1.5}],"overall_relevance":-0.1,"decision":"keep"}'
    out = model_client.parse_stage1_json(raw, "x")
    assert out["topics"][0]["relevance"] == 1.0
    assert out["overall_relevance"] == 0.0


def test_parse_stage1_invalid_json():
    with pytest.raises(ValueError, match="JSON"):
        model_client.parse_stage1_json("not json", "x")


def test_parse_stage2_json():
    raw = '''{"paper_id":"2401.2","title":"T","categories":["cs.LG"],"problem":"P","motivation":"M","key_challenges":["C1"],"approach":"A","assumptions_limitations":[],"evidence_results":["E1"],"takeaways":["t1","t2","t3"]}'''
    out = model_client.parse_stage2_json(raw, "2401.2")
    assert out["paper_id"] == "2401.2"
    assert out["takeaways"] == ["t1", "t2", "t3"]
    assert out["key_challenges"] == ["C1"]


def test_build_stage1_prompt():
    topics = [{"id": "anns", "name": "ANNS", "description": "Nearest neighbor search", "keywords": []}]
    paper = {"arxiv_id": "2401.1", "title": "A Paper", "categories": ["cs.LG"], "published": "2024-01-01", "abstract": "We propose..."}
    msgs = model_client.build_stage1_prompt(topics, paper)
    assert len(msgs) == 2
    assert "anns" in msgs[1]["content"]
    assert "A Paper" in msgs[1]["content"]
