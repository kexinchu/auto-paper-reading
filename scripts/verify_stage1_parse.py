#!/usr/bin/env python3
"""
向本地 vLLM 发送 Stage1 请求，获取原始输出，用当前解析逻辑验证是否能正确得到打分。
始终把 raw 保存到 logs/debug_stage1_<id>.raw.txt，便于定位问题。
用法: 在项目根目录执行
  PYTHONPATH=. python3 scripts/verify_stage1_parse.py [arxiv_id]
  arxiv_id 可选，默认 2603.09999v1
需要: config + topics + vLLM
"""

import json
import re
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from openai import OpenAI

from src.config import load_config
from src.topics import load_topics
from src import model_client


def save_raw(paper_id: str, raw: str, log_dir: Path) -> Path:
    """Save raw LLM output for debugging. Returns path to .raw.txt."""
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^\w\-.]", "_", paper_id)
    path = log_dir / f"debug_stage1_{safe_id}.raw.txt"
    path.write_text(raw or "(empty)", encoding="utf-8")
    print("Saved raw to", path, file=sys.stderr)
    return path


def main() -> int:
    paper_id = sys.argv[1] if len(sys.argv) > 1 else "2603.09999v1"
    config_path = REPO / "config" / "config_kexin.yaml"
    if not config_path.exists():
        config_path = REPO / "config" / "config.yaml"
    topics_path = REPO / "config" / "topics.yaml"
    if not config_path.exists() or not topics_path.exists():
        print("Missing config or topics file", file=sys.stderr)
        return 1

    config = load_config(config_path)
    topics_list = load_topics(topics_path)
    model_cfg = config["model"]
    base_url = model_cfg.get("base_url", "http://127.0.0.1:8000/v1").rstrip("/")
    model_name = model_cfg.get("model_name", "Qwen3.5-35B-A3B-GPTQ-Int4")
    api_key = model_cfg.get("api_key") or "dummy"
    timeout_s = model_cfg.get("timeout_s", 120)
    enable_thinking = model_cfg.get("enable_thinking", True)
    extra_body = None if enable_thinking else {"chat_template_kwargs": {"enable_thinking": False}}
    log_dir = REPO / "logs"

    paper = {
        "arxiv_id": paper_id,
        "title": "Efficient KV-Cache Compression for Large Language Model Inference",
        "categories": ["cs.LG", "cs.CL"],
        "published": "2026-03-01",
        "abstract": "We propose a method to compress KV-cache in transformer inference, reducing memory and improving throughput for LLM serving.",
    }

    client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)
    messages = model_client.build_stage1_prompt(topics_list, paper)

    print("Sending Stage1 request to vLLM...")
    print("Model:", model_name, "enable_thinking:", enable_thinking)
    print("Paper id:", paper["arxiv_id"])
    try:
        raw = model_client.chat_completion(
            client,
            model_name=model_name,
            messages=messages,
            temperature=0,
            max_tokens=stage1_max_tokens,
            timeout_s=timeout_s,
            max_retries=2,
            extra_body=extra_body,
        )
    except Exception as e:
        print("LLM request failed:", e, file=sys.stderr)
        traceback.print_exc()
        return 2

    save_raw(paper["arxiv_id"], raw, log_dir)
    print("\n--- Raw LLM output (first 800 chars) ---")
    print(raw[:800])
    if len(raw) > 800:
        print("... [truncated, full in logs/]")
    print("\n--- Parsing: parse_stage1_json ---")
    try:
        data = model_client.parse_stage1_json(raw, paper["arxiv_id"])
        print("OK: Parse succeeded.")
        print("paper_id:", data.get("paper_id"))
        print("decision:", data.get("decision"))
        print("overall_relevance:", data.get("overall_relevance"))
        topics = data.get("topics", [])
        print("topics (count):", len(topics))
        for t in topics[:3]:
            print("  -", t.get("topic_id"), "relevance:", t.get("relevance"))
        if len(topics) > 3:
            print("  ...")
        print("\nFull parsed JSON (compact):")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:1500])
        return 0
    except ValueError as e:
        print("FAIL: parse_stage1_json:", e, file=sys.stderr)
        traceback.print_exc()
        print("\n--- Trying try_parse_stage1_aggressive ---", file=sys.stderr)
        data, err = model_client.try_parse_stage1_aggressive(raw, paper["arxiv_id"])
        if data is not None:
            print("OK: Aggressive parse recovered.", file=sys.stderr)
            print("paper_id:", data.get("paper_id"), "decision:", data.get("decision"))
            return 0
        print("Aggressive parse also failed:", err, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
