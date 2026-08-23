"""Tests for idea exploration parse, focus filter, and screening merge."""

from pathlib import Path

from src import ideas, model_client
from src.topics import load_topics


def test_load_focus_topics_yaml():
    path = Path(__file__).resolve().parent.parent / "config" / "topics.yaml"
    topics = load_topics(path)
    ids = [t["id"] for t in topics]
    assert ids == ["ann-retrieval-systems", "systems-memory", "agent-os"]


def test_filter_focus_summaries():
    topics = [
        {"id": "ann-retrieval-systems", "name": "ANNS"},
        {"id": "systems-memory", "name": "Memory"},
        {"id": "agent-os", "name": "Agent OS"},
    ]
    papers = [
        {
            "paper_id": "a",
            "topics": [{"topic_id": "ann-retrieval-systems", "relevance": 0.8}],
        },
        {
            "paper_id": "b",
            "topics": [{"topic_id": "llm-opt", "relevance": 0.95}],
        },
        {
            "paper_id": "c",
            "topics": [{"topic_id": "agent-os", "relevance": 0.4}],
        },
    ]
    kept, dropped = ideas.filter_focus_summaries(papers, topics, threshold=0.7)
    assert [p["paper_id"] for p in kept] == ["a"]
    assert {p["paper_id"] for p in dropped} == {"b", "c"}


def test_parse_ideas_json():
    raw = """
    <think>先看 ANNS 和 memory 的交叉</think>
    {
      "thinking": "DiskANN 与 CXL 之间有组合空间。",
      "ideas": [{
        "idea_id": "cxl-ann",
        "title": "CXL 上的分层 ANN",
        "topic_ids": ["ann-retrieval-systems", "systems-memory"],
        "statement": "把热图放在本机、冷边放 CXL。",
        "motivation": "本批论文分别做了磁盘索引和 CXL 池化。",
        "approach_sketch": "按访问频率分层迁移邻接。",
        "gap": "磁盘 ANN 没处理 CXL 延迟抖动",
        "experiments": ["对照 DiskANN，测 CXL 延迟下 recall"],
        "risks": ["CXL 带宽不够撑边访问"],
        "not_a_reimplementation": "不是再做一层磁盘索引，而是按 CXL 延迟分层",
        "search_query": "CXL disaggregated memory ANN index",
        "related_papers": [
          {"paper_id": "2401.1", "relation": "gaps", "note": "只做磁盘，不做 CXL"}
        ],
        "potential": {"score": 0.8, "novelty": "moderate", "impact": "serving 成本",
                      "feasibility": "medium", "why": "硬件已到"},
        "scope": {"verdict": "just_right", "horizon": "conference", "why": "一个系统论文"},
        "decision": "pursue",
        "decision_reason": "缺口清楚，scope 合适"
      }]
    }
    """
    out = model_client.parse_ideas_json(raw, ["2401.1", "2401.2"])
    assert "组合空间" in out["thinking"]
    idea = out["ideas"][0]
    assert idea["idea_id"] == "cxl-ann"
    assert idea["decision"] == "pursue"
    assert idea["related_papers"][0]["paper_id"] == "2401.1"
    assert idea["potential"]["score"] == 0.8
    assert idea["scope"]["verdict"] == "just_right"
    assert idea["gap"].startswith("磁盘 ANN")
    assert idea["experiments"][0].startswith("对照 DiskANN")
    assert "不是再做" in idea["not_a_reimplementation"]


def test_parse_ideas_drops_unknown_related_ids():
    raw = """{
      "thinking": "t",
      "ideas": [{
        "title": "X",
        "statement": "一个想法",
        "related_papers": [{"paper_id": "ghost", "relation": "overlaps"}],
        "decision": "watch"
      }]
    }"""
    out = model_client.parse_ideas_json(raw, ["2401.1"])
    assert out["ideas"][0]["related_papers"] == []
    assert out["ideas"][0]["decision"] == "watch"


def test_merge_screened_keeps_all_original_ideas():
    original = {
        "thinking": "初筛",
        "ideas": [
            {"idea_id": "a", "title": "A", "decision": "pursue", "potential": {"score": 0.9}},
            {"idea_id": "b", "title": "B", "decision": "watch", "potential": {"score": 0.5}},
        ],
    }
    screened = {
        "thinking": "外部工作已覆盖 A",
        "ideas": [
            {
                "idea_id": "a",
                "decision": "drop",
                "decision_reason": "已被覆盖",
                "potential": {"score": 0.3},
                "external_related": [{"title": "Old Paper", "overlap": "核心主张相同"}],
            }
        ],
    }
    out = ideas._merge_screened(original, screened)
    assert [i["idea_id"] for i in out["ideas"]] == ["b", "a"]  # watch then drop
    by_id = {i["idea_id"]: i for i in out["ideas"]}
    assert by_id["a"]["decision"] == "drop"
    assert by_id["b"]["title"] == "B"
    assert out["thinking"] == "外部工作已覆盖 A"


def test_build_ideas_propose_prompt():
    topics = [{"id": "agent-os", "name": "Agent OS", "description": "runtime"}]
    papers = [{"paper_id": "2401.1", "title": "AIOS", "takeaways": ["调度"]}]
    msgs = model_client.build_ideas_propose_prompt(topics, papers, None, max_ideas=4)
    blob = msgs[0]["content"] + msgs[1]["content"]
    assert "Agent OS" in blob
    assert "2401.1" in blob
    assert "scope" in blob.lower()
    assert "默认观察" in blob
    assert "不是复现因为" in blob


def test_select_seed_summaries_prefers_close_reads():
    papers = [
        {
            "paper_id": "low",
            "title": "Low",
            "topics": [{"topic_id": "agent-os", "relevance": 0.71}],
            "takeaways": ["次要"],
        },
        {
            "paper_id": "must",
            "title": "Must",
            "topics": [{"topic_id": "agent-os", "relevance": 0.8}],
            "takeaways": ["先读"],
        },
        {
            "paper_id": "deep",
            "title": "Deep",
            "topics": [{"topic_id": "agent-os", "relevance": 0.75}],
            "takeaways": ["精读"],
        },
    ]
    briefing = {
        "clusters": [{
            "close_reads": [{"paper_id": "deep"}],
            "must_read": [{"paper_id": "must"}],
        }],
    }
    seeds, catalog = ideas.select_seed_summaries(papers, briefing, max_deep=2)
    assert [p["paper_id"] for p in seeds] == ["deep", "must"]
    assert [p["paper_id"] for p in catalog] == ["low"]
