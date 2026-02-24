"""Tests for model_client: JSON parsing, prompt building, and live LLM call."""

import pytest
from pathlib import Path

from src import model_client
from src.config import load_config


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


def test_parse_stage1_json_with_think_tag():
    """Model returns think-tag block then JSON; we strip think and parse."""
    raw = (
        "<think>\nOkay, let's tackle this. The paper is about X.\n</think>\n"
        '{"paper_id": "2602.20133v1", "topics": [{"topic_id": "llm-opt", "relevance": 0.8, "reason": "LLM related"}], '
        '"overall_relevance": 0.8, "decision": "keep"}'
    )
    out = model_client.parse_stage1_json(raw, "2602.20133v1")
    assert out["paper_id"] == "2602.20133v1"
    assert out["decision"] == "keep"
    assert out["topics"][0]["topic_id"] == "llm-opt"


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


def test_call_local_llm():
    """Call local LLM (vLLM) using config; requires server at base_url.
    Uses model id from GET /v1/models when config id returns 404."""
    config_path = Path(__file__).resolve().parent.parent / "config" / "config.yaml"
    if not config_path.exists():
        pytest.skip(f"Config not found: {config_path}")
    config = load_config(config_path)
    model_cfg = config["model"]
    base_url = model_cfg["base_url"].rstrip("/")
    model_name = model_cfg["model_name"]
    api_key = model_cfg.get("api_key") or "dummy"
    timeout_s = model_cfg.get("timeout_s", 60)

    from openai import OpenAI
    client = OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout_s,
    )
    messages = [{"role": "user", "content": "Reply with exactly: OK"}]

    try:
        reply = model_client.chat_completion(
            client,
            model_name=model_name,
            messages=messages,
            temperature=0,
            max_tokens=20,
            timeout_s=timeout_s,
            max_retries=2,
        )
    except Exception as e:
        if "404" in str(e) or "does not exist" in str(e):
            import requests
            r = requests.get(f"{base_url}/models", timeout=10)
            if r.status_code != 200:
                pytest.skip(f"Local LLM not available: {e}")
            data = r.json()
            models = data.get("data") or []
            if not models:
                pytest.skip(f"No models listed at {base_url}/models")
            model_name = models[0]["id"]
            reply = model_client.chat_completion(
                client,
                model_name=model_name,
                messages=messages,
                temperature=0,
                max_tokens=20,
                timeout_s=timeout_s,
                max_retries=2,
            )
        else:
            raise
    assert isinstance(reply, str)
    assert len(reply.strip()) > 0
