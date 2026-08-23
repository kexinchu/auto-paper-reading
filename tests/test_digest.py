"""Tests for Stage-3 topic clustering and briefing helpers."""

from src import digest, model_client


TOPICS = [
    {"id": "llm-opt", "name": "LLM 系统优化", "description": "serving"},
    {"id": "systems-memory", "name": "内存与互连", "description": "CXL"},
    {"id": "rag-systems", "name": "RAG 系统", "description": "RAG"},
]


def _paper(pid: str, title: str, topic: str, rel: float = 0.9, takeaway: str = "要点") -> dict:
    return {
        "paper_id": pid,
        "title": title,
        "published": "2026-08-17",
        "topics": [{"topic_id": topic, "relevance": rel}],
        "problem": "问题描述",
        "approach": "方法描述",
        "takeaways": [takeaway],
    }


def test_compact_paper_for_prompt():
    paper = _paper("2401.1", "A long title", "llm-opt", takeaway="吞吐提升")
    out = digest.compact_paper_for_prompt(paper)
    assert out["paper_id"] == "2401.1"
    assert out["primary_topic"] == "llm-opt"
    assert out["takeaways"] == ["吞吐提升"]
    assert out["topics"][0]["relevance"] == 0.9


def test_rich_paper_for_prompt_keeps_limitations():
    paper = _paper("2401.1", "A long title", "llm-opt", takeaway="吞吐提升")
    paper["motivation"] = "显存墙"
    paper["key_challenges"] = ["HBM 带宽"]
    paper["assumptions_limitations"] = ["只测 offline"]
    paper["evidence_results"] = ["QPS +20%"]
    out = digest.rich_paper_for_prompt(paper)
    assert out["motivation"] == "显存墙"
    assert out["key_challenges"] == ["HBM 带宽"]
    assert out["assumptions_limitations"] == ["只测 offline"]
    assert out["evidence_results"] == ["QPS +20%"]


def test_fallback_digest_groups_by_primary_topic():
    papers = [
        _paper("a", "Paper A", "llm-opt"),
        _paper("b", "Paper B", "rag-systems"),
        _paper("c", "Paper C", "llm-opt"),
    ]
    out = digest.fallback_digest(papers, TOPICS)
    assert out["fallback"] is True
    ids = [c["cluster_id"] for c in out["clusters"]]
    assert ids == ["llm-opt", "rag-systems"]
    llm_cluster = out["clusters"][0]
    assert {p["paper_id"] for p in llm_cluster["papers"]} == {"a", "c"}


def test_ensure_all_papers_placed_adds_missing():
    briefing = {
        "overview": "x",
        "thinking": "y",
        "clusters": [{
            "cluster_id": "serving",
            "title": "Serving",
            "topic_ids": ["llm-opt"],
            "why_grouped": "",
            "narrative": "",
            "trends": [],
            "divergences": [],
            "must_read": [],
            "papers": [{"paper_id": "a", "one_liner": "已覆盖"}],
        }],
    }
    papers = [
        _paper("a", "Paper A", "llm-opt"),
        _paper("b", "Paper B", "llm-opt", takeaway="被漏掉的要点"),
        _paper("c", "Paper C", "rag-systems", takeaway="另一主题"),
    ]
    out = digest.ensure_all_papers_placed(briefing, papers, TOPICS)
    serving_ids = {p["paper_id"] for p in out["clusters"][0]["papers"]}
    assert serving_ids == {"a", "b"}
    other = [c for c in out["clusters"] if c["cluster_id"] == "other"]
    assert len(other) == 1
    assert other[0]["papers"][0]["paper_id"] == "c"


def test_parse_stage3_digest_json():
    raw = """
    <think>先把 serving 和 memory 放一起</think>
    {
      "overview": "今日主线是推理 Serving。",
      "thinking": "llm-opt 与 systems-memory 在本批汇合。",
      "clusters": [{
        "cluster_id": "serving-memory",
        "title": "推理 Serving 与内存",
        "topic_ids": ["llm-opt", "systems-memory"],
        "why_grouped": "同时讨论调度与 HBM",
        "narrative": "本批工作围绕吞吐与显存墙。",
        "trends": ["前缀缓存"],
        "divergences": ["离线 vs 在线量化"],
        "must_read": [{"paper_id": "2401.1", "why": "系统最完整"}],
        "close_reads": [{
          "paper_id": "2401.1",
          "mechanism": "按前缀命中重排调度队列",
          "limitation": "假设请求可预测",
          "open_question": "在线负载下是否仍成立",
          "why_first": "机制最完整"
        }],
        "papers": [
          {"paper_id": "2401.1", "one_liner": "提出新调度"},
          {"paper_id": "2401.2", "one_liner": "CXL 卸载 KV"}
        ]
      }]
    }
    """
    out = model_client.parse_stage3_digest_json(raw, ["2401.1", "2401.2", "2401.3"])
    assert out["overview"].startswith("今日主线")
    assert "汇合" in out["thinking"]
    assert out["clusters"][0]["title"] == "推理 Serving 与内存"
    assert [p["paper_id"] for p in out["clusters"][0]["papers"]] == ["2401.1", "2401.2"]
    assert out["clusters"][0]["close_reads"][0]["mechanism"].startswith("按前缀")


def test_parse_stage3_drops_unknown_and_duplicate_ids():
    raw = """{
      "overview": "o",
      "thinking": "t",
      "clusters": [{
        "cluster_id": "c1",
        "title": "线索",
        "topic_ids": ["llm-opt"],
        "papers": [
          {"paper_id": "2401.1", "one_liner": "一"},
          {"paper_id": "ghost", "one_liner": "不存在"},
          {"paper_id": "2401.1", "one_liner": "重复"}
        ]
      }]
    }"""
    out = model_client.parse_stage3_digest_json(raw, ["2401.1"])
    assert [p["paper_id"] for p in out["clusters"][0]["papers"]] == ["2401.1"]


def test_build_stage3_digest_prompt_is_chinese():
    papers = [digest.compact_paper_for_prompt(_paper("2401.1", "T", "llm-opt"))]
    msgs = model_client.build_stage3_digest_prompt(TOPICS, papers)
    blob = msgs[0]["content"] + msgs[1]["content"]
    assert "简体中文" in blob
    assert "研究线索" in blob
    assert "close_reads" in blob
    assert "2401.1" in msgs[1]["content"]
    assert "llm-opt" in msgs[1]["content"]
