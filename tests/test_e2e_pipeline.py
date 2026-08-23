"""
End-to-end pipeline test: real orchestration, mocked network/LLM/SMTP.
Covers keyword filter, focus-topic filter, Stage1–4, single briefing email, ideas.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src import db
from src.pipeline import run_pipeline

REPO = Path(__file__).resolve().parent.parent
TOPICS_PATH = REPO / "config" / "topics.yaml"

LONG_ANN = (
    "We present a GPU ANN search system using HNSW and DiskANN style graph indexes "
    "for billion-scale vector search with a recall-latency tradeoff. "
) * 8
LONG_MEM = (
    "This paper studies CXL memory disaggregation and tiered memory for HBM "
    "bandwidth walls and GPU memory management in AI infrastructure. "
) * 8
LONG_AGENT = (
    "We design an agent operating system (Agent OS / AIOS) with scheduling, "
    "sandbox execution, tool calling as syscalls, and an agent memory system. "
) * 8
LONG_WEAK = (
    "We mention HNSW only in passing while studying a vision transformer for cats. "
) * 8


def _paper(arxiv_id: str, title: str, abstract: str, categories: list[str] | None = None) -> dict:
    return {
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": ["Ada"],
        "categories": categories or ["cs.IR"],
        "published": "2026-08-17",
        "updated": "2026-08-17",
        "abstract": abstract,
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
    }


FETCHED = [
    _paper("2601.00001", "GPU DiskANN Serving", LONG_ANN, ["cs.IR"]),
    _paper("2601.00002", "CXL Tiered Memory for AI", LONG_MEM, ["cs.AR"]),
    _paper("2601.00003", "AIOS: An Agent Operating System", LONG_AGENT, ["cs.OS"]),
    _paper("2601.00004", "A Study of Household Cats", "Cats sleep a lot and chase yarn.", ["cs.AI"]),
    _paper("2601.00005", "ViT for Pets", LONG_WEAK, ["cs.LG"]),
    _paper("2601.00006", "Already Emailed ANN", LONG_ANN, ["cs.IR"]),
]


def _stage1_json(paper_id: str, topic_id: str, relevance: float) -> str:
    topics = [
        {"topic_id": "ann-retrieval-systems", "relevance": 0.0, "reason": "n/a"},
        {"topic_id": "systems-memory", "relevance": 0.0, "reason": "n/a"},
        {"topic_id": "agent-os", "relevance": 0.0, "reason": "n/a"},
    ]
    for t in topics:
        if t["topic_id"] == topic_id:
            t["relevance"] = relevance
            t["reason"] = "match"
    decision = "keep" if relevance >= 0.8 else "drop"
    return json.dumps({
        "paper_id": paper_id,
        "topics": topics,
        "overall_relevance": relevance,
        "decision": decision,
    }, ensure_ascii=False)


def _stage2_json(paper_id: str, title: str, topic_id: str) -> str:
    return json.dumps({
        "paper_id": paper_id,
        "title": title,
        "categories": ["cs.IR"],
        "published": "2026-08-17",
        "topics": [{"topic_id": topic_id, "relevance": 0.95}],
        "problem": "系统瓶颈",
        "motivation": "现有方案不够",
        "key_challenges": ["延迟", "成本"],
        "approach": "提出新的系统机制",
        "assumptions_limitations": ["未明确报告"],
        "evidence_results": ["吞吐提升"],
        "takeaways": ["要点一", "要点二", "要点三"],
    }, ensure_ascii=False)


STAGE1_BY_TITLE = {
    "GPU DiskANN Serving": ("2601.00001", "ann-retrieval-systems", 0.95),
    "CXL Tiered Memory for AI": ("2601.00002", "systems-memory", 0.95),
    "AIOS: An Agent Operating System": ("2601.00003", "agent-os", 0.95),
    "ViT for Pets": ("2601.00005", "ann-retrieval-systems", 0.2),
}


def _stage3_json() -> str:
    return json.dumps({
        "overview": "今日三条线分别是 ANNS、内存与 Agent OS。",
        "thinking": "检索系统与 CXL 分层有交叉；Agent OS 相对独立。",
        "clusters": [
            {
                "cluster_id": "ann-mem",
                "title": "ANNS 与分层内存",
                "topic_ids": ["ann-retrieval-systems", "systems-memory"],
                "why_grouped": "索引放置与 CXL 相关",
                "narrative": "本批同时出现图索引 Serving 与 CXL 分层。",
                "trends": ["异构内存上的索引"],
                "divergences": ["GPU ANN vs CXL 池化"],
                "must_read": [{"paper_id": "2601.00001", "why": "系统最完整"}],
                "close_reads": [{
                    "paper_id": "2601.00001",
                    "mechanism": "GPU 上驻留热图，磁盘放冷边",
                    "limitation": "假设访问倾斜稳定",
                    "open_question": "CXL 延迟下召回如何掉",
                    "why_first": "系统最完整",
                }],
                "papers": [
                    {"paper_id": "2601.00001", "one_liner": "GPU DiskANN Serving"},
                    {"paper_id": "2601.00002", "one_liner": "CXL 分层内存"},
                ],
            },
            {
                "cluster_id": "agent-os",
                "title": "Agent OS 运行时",
                "topic_ids": ["agent-os"],
                "why_grouped": "独立线索",
                "narrative": "把 Agent 当操作系统来做。",
                "trends": ["工具即 syscall"],
                "divergences": [],
                "must_read": [{"paper_id": "2601.00003", "why": "运行时抽象清楚"}],
                "papers": [
                    {"paper_id": "2601.00003", "one_liner": "AIOS 调度与沙箱"},
                ],
            },
        ],
    }, ensure_ascii=False)


def _ideas_propose_json() -> str:
    return json.dumps({
        "thinking": "CXL 上放 ANN 冷边值得做；纯复现 AIOS 应放下。",
        "ideas": [
            {
                "idea_id": "cxl-ann",
                "title": "CXL 上的分层 ANN",
                "topic_ids": ["ann-retrieval-systems", "systems-memory"],
                "statement": "热图在本机，冷边在 CXL。",
                "motivation": "本批分别做了 GPU ANN 和 CXL，没有合在一起。",
                "approach_sketch": "按访问频率迁移邻接表。",
                "gap": "GPU ANN 没处理 CXL 延迟抖动",
                "experiments": ["对照 DiskANN，测 CXL 延迟下 recall"],
                "risks": ["CXL 带宽不够撑边访问"],
                "not_a_reimplementation": "不是再做 GPU 索引，而是按 CXL 延迟分层",
                "search_query": "CXL disaggregated memory ANN index",
                "related_papers": [
                    {"paper_id": "2601.00001", "relation": "gaps", "note": "只做 GPU"},
                    {"paper_id": "2601.00002", "relation": "extends", "note": "提供 CXL 层"},
                ],
                "potential": {
                    "score": 0.82, "novelty": "moderate", "impact": "检索成本",
                    "feasibility": "medium", "why": "硬件已到",
                },
                "scope": {"verdict": "just_right", "horizon": "conference", "why": "一篇系统论文"},
                "decision": "pursue",
                "decision_reason": "缺口清楚",
            },
            {
                "idea_id": "rehash-aios",
                "title": "再做一个通用 Agent OS",
                "topic_ids": ["agent-os"],
                "statement": "重新实现 AIOS。",
                "motivation": "本批已有 AIOS。",
                "approach_sketch": "复现调度与沙箱。",
                "search_query": "AIOS agent operating system",
                "related_papers": [
                    {"paper_id": "2601.00003", "relation": "overlaps", "note": "已被覆盖"},
                ],
                "potential": {
                    "score": 0.2, "novelty": "incremental", "impact": "低",
                    "feasibility": "high", "why": "没有新主张",
                },
                "scope": {"verdict": "too_broad", "horizon": "system", "why": "口号过大"},
                "decision": "drop",
                "decision_reason": "已被本批覆盖",
            },
        ],
    }, ensure_ascii=False)


def _ideas_screen_json() -> str:
    data = json.loads(_ideas_propose_json())
    data["thinking"] = "外部工作未覆盖 CXL+ANN 组合，维持值得跟。"
    data["ideas"][0]["external_related"] = [
        {"title": "DiskANN", "year": "2019", "url": "https://example.com/diskann", "overlap": "磁盘层次可借鉴"},
    ]
    data["ideas"][0]["decision_reason"] = "外部工作只覆盖磁盘层，未做 CXL。"
    return json.dumps(data, ensure_ascii=False)


def _fake_chat(_client, _model, messages, **_kwargs) -> str:
    blob = "\n".join(m.get("content") or "" for m in messages)
    if "上一份回复无法解析" in blob:
        raise AssertionError("e2e mock should not hit JSON repair")
    if "idea 评审" in blob or "外部相关工作更新" in blob:
        return _ideas_screen_json()
    if "idea exploration" in blob or "可跟的 idea" in blob:
        return _ideas_propose_json()
    if "按研究线索阅读" in blob or ("研究线索" in blob and "cluster" in blob):
        return _stage3_json()
    if "structured summary" in blob or "Full text (extract)" in blob:
        for title, (pid, topic, _) in STAGE1_BY_TITLE.items():
            if title in blob:
                return _stage2_json(pid, title, topic)
        raise AssertionError(f"unmatched stage2 prompt: {blob[:200]}")
    for title, (pid, topic, rel) in STAGE1_BY_TITLE.items():
        if title in blob:
            return _stage1_json(pid, topic, rel)
    raise AssertionError(f"unmatched LLM prompt: {blob[:240]}")


def _write_config(tmp: Path, *, idea_enabled: bool = True, digest_mode: str = "topic_briefing") -> Path:
    cfg = {
        "arxiv": {"categories": ["cs.IR"], "max_results_per_category": 5, "days_back": 1},
        "semantic_scholar": {
            "enabled": True,
            "queries": ["approximate nearest neighbor"],
            "limit": 2,
            "delay_between_queries": 0,
        },
        "blogs": {
            "enabled": True,
            "days_back": 3,
            "delay_between_sources": 0,
            "sources": [{"name": "Lab", "type": "rss", "url": "https://example.com/rss", "max_entries": 2}],
        },
        "model": {
            "base_url": "http://127.0.0.1:9/v1",
            "api_key": "dummy",
            "model_name": "mock-model",
            "stage1_workers": 1,
            "stage1_batch_size": 1,
            "temperature": 0,
            "timeout_s": 5,
            "enable_thinking": False,
            "digest_enable_thinking": True,
            "digest_max_tokens": 2048,
        },
        "thresholds": {
            "relevance": 0.7,
            "abstract_only_relevance": 0.92,
            "abstract_min_length": 500,
        },
        "storage": {
            "db_path": str(tmp / "arxiv.db"),
            "pdf_dir": str(tmp / "pdfs"),
            "text_dir": str(tmp / "text"),
            "save_text": False,
        },
        "email": {
            "smtp_host": "smtp.test.local",
            "smtp_port": 25,
            "from_addr": "a@test.local",
            "to_addr": "b@test.local",
            "use_tls": False,
            "digest_mode": digest_mode,
        },
        "idea_exploration": {
            "enabled": idea_enabled,
            "max_ideas": 6,
            "related_search_enabled": True,
            "related_limit": 3,
            "related_delay_s": 0,
        },
    }
    path = tmp / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def _seed_db(db_path: Path) -> None:
    db.ensure_db(db_path)
    db.upsert_paper_metadata(db_path, "2601.00006", "Already Emailed ANN", "cs.IR", db.NEW)
    db.mark_status(db_path, "2601.00006", db.EMAILED)
    db.upsert_paper_metadata(db_path, "2401.old01", "Old LLM Opt Paper", "cs.LG", db.NEW)
    old_summary = {
        "paper_id": "2401.old01",
        "title": "Old LLM Opt Paper",
        "topics": [{"topic_id": "llm-opt", "relevance": 0.99}],
        "takeaways": ["旧主题不应进入焦点汇报"],
    }
    db.mark_status(
        db_path, "2401.old01", db.STAGE2_OK,
        stage2_json=json.dumps(old_summary, ensure_ascii=False),
    )


@pytest.fixture
def e2e_env(tmp_path, monkeypatch):
    sent: list[dict] = []

    def capture_email(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr("src.arxiv_client.fetch_papers", lambda **kwargs: list(FETCHED))
    monkeypatch.setattr("src.semantic_scholar_client.fetch_papers", lambda **kwargs: [])
    monkeypatch.setattr(
        "src.semantic_scholar_client.search_related",
        lambda query, limit=5, **kwargs: [{
            "paper_id": "semantic_scholar:diskann",
            "title": "DiskANN",
            "year": "2019",
            "url": "https://example.com/diskann",
            "abstract": "SSD graph index",
            "citation_count": 100,
        }],
    )
    monkeypatch.setattr(
        "src.blog_client.fetch_all_blogs",
        lambda sources, days_back=3, delay_between_sources=2.0: [{
            "id": "blog-1",
            "title": "Lab notes on ANN",
            "url": "https://example.com/blog/ann",
            "summary": "A short lab note",
            "published": "2026-08-16",
            "source": "Lab",
        }],
    )
    monkeypatch.setattr("src.model_client.chat_completion", _fake_chat)
    monkeypatch.setattr("src.model_client.SERVER_RESTART_WAIT_S", 0)
    monkeypatch.setattr("src.emailer.send_digest_email", capture_email)

    cfg_path = _write_config(tmp_path)
    _seed_db(Path(tmp_path / "arxiv.db"))
    return {"tmp": tmp_path, "config": cfg_path, "sent": sent, "db": tmp_path / "arxiv.db"}


def test_e2e_topic_briefing_and_ideas(e2e_env):
    stats = run_pipeline(e2e_env["config"], TOPICS_PATH)

    assert stats["total"] == 6
    assert stats["skipped_existing"] == 1
    assert stats["skipped_keyword"] == 1
    assert stats["stage1_run"] == 4
    assert stats["stage1_failed"] == 0
    assert stats["skipped_irrelevant"] == 1
    assert stats["relevant"] == 3
    assert stats["abstract_only"] == 3
    assert stats["stage2_ok"] == 3
    assert stats["stage2_failed"] == 0
    assert stats["skipped_off_focus"] == 1
    assert stats["ideas_explored"] == 2
    assert stats["emailed"] == 3
    assert stats.get("blogs_emailed") == 1

    assert len(e2e_env["sent"]) == 1
    mail = e2e_env["sent"][0]
    assert mail["is_html"] is True
    assert mail["subject"].startswith("[AI 脉络]")
    assert "3 篇论文" in mail["subject"]
    assert "2 个想法" in mail["subject"]
    assert "1 篇博客" in mail["subject"]
    assert "第 " not in mail["subject"]

    html = mail["body"]
    assert "今日论文脉络" in html
    assert "今日判断" in html
    assert "ANNS 与分层内存" in html
    assert "Agent OS 运行时" in html
    assert "想法探索" in html
    assert "值得跟" in html
    assert "放下" in html
    assert "CXL 上的分层 ANN" in html
    assert "再做一个通用 Agent OS" in html
    assert "本批相关论文" in html
    assert "外部相关工作" in html
    assert "DiskANN" in html
    assert "精读" in html
    assert "机制缺口" in html
    assert "可做实验" in html
    assert "Lab notes on ANN" in html
    assert "Old LLM Opt Paper" not in html
    assert "A Study of Household Cats" not in html
    assert "ViT for Pets" not in html
    assert '<div class="section-title">问题</div>' not in html

    db_path = e2e_env["db"]
    assert db.get_status(db_path, "2601.00001") == db.EMAILED
    assert db.get_status(db_path, "2601.00002") == db.EMAILED
    assert db.get_status(db_path, "2601.00003") == db.EMAILED
    assert db.get_status(db_path, "2601.00004") == db.SKIPPED
    assert db.get_status(db_path, "2601.00005") == db.SKIPPED
    assert db.get_status(db_path, "2601.00006") == db.EMAILED
    assert db.get_status(db_path, "2401.old01") == db.SKIPPED

    # Second run is idempotent: no new email
    stats2 = run_pipeline(e2e_env["config"], TOPICS_PATH)
    assert stats2["emailed"] == 0
    assert stats2["skipped_existing"] >= 1
    assert len(e2e_env["sent"]) == 1


def test_e2e_stage3_failure_still_sends_one_email_with_ideas(tmp_path, monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr("src.arxiv_client.fetch_papers", lambda **kwargs: FETCHED[:3])
    monkeypatch.setattr("src.semantic_scholar_client.fetch_papers", lambda **kwargs: [])
    monkeypatch.setattr("src.semantic_scholar_client.search_related", lambda *a, **k: [])
    monkeypatch.setattr("src.blog_client.fetch_all_blogs", lambda *a, **k: [])
    monkeypatch.setattr("src.emailer.send_digest_email", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr("src.model_client.SERVER_RESTART_WAIT_S", 0)

    def flaky_chat(_c, _m, messages, **_k):
        blob = "\n".join(x.get("content") or "" for x in messages)
        if "研究线索" in blob and "cluster" in blob:
            return "not-json"
        return _fake_chat(_c, _m, messages)

    monkeypatch.setattr("src.model_client.chat_completion", flaky_chat)
    cfg = _write_config(tmp_path)
    stats = run_pipeline(cfg, TOPICS_PATH)

    assert stats["emailed"] == 3
    assert stats["ideas_explored"] == 2
    assert len(sent) == 1
    html = sent[0]["body"]
    assert "交叉综述未能生成" in html or "按预设主题分组" in html
    assert "想法探索" in html
    assert "GPU DiskANN Serving" in html


def test_e2e_ideas_disabled_omits_idea_section(tmp_path, monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr("src.arxiv_client.fetch_papers", lambda **kwargs: FETCHED[:3])
    monkeypatch.setattr("src.semantic_scholar_client.fetch_papers", lambda **kwargs: [])
    monkeypatch.setattr("src.blog_client.fetch_all_blogs", lambda *a, **k: [])
    monkeypatch.setattr("src.emailer.send_digest_email", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr("src.model_client.chat_completion", _fake_chat)
    monkeypatch.setattr("src.model_client.SERVER_RESTART_WAIT_S", 0)
    cfg = _write_config(tmp_path, idea_enabled=False)
    stats = run_pipeline(cfg, TOPICS_PATH)
    assert stats["emailed"] == 3
    assert stats["ideas_explored"] == 0
    assert len(sent) == 1
    assert 'id="ideas"' not in sent[0]["body"]
    assert "值得跟" not in sent[0]["body"]
    assert "个想法" not in sent[0]["subject"]
    assert sent[0]["subject"].startswith("[AI 脉络]")


def test_e2e_per_paper_mode_still_sends_digest(tmp_path, monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr("src.arxiv_client.fetch_papers", lambda **kwargs: FETCHED[:3])
    monkeypatch.setattr("src.semantic_scholar_client.fetch_papers", lambda **kwargs: [])
    monkeypatch.setattr("src.blog_client.fetch_all_blogs", lambda *a, **k: [])
    monkeypatch.setattr("src.emailer.send_digest_email", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr("src.model_client.chat_completion", _fake_chat)
    monkeypatch.setattr("src.model_client.SERVER_RESTART_WAIT_S", 0)
    cfg = _write_config(tmp_path, idea_enabled=False, digest_mode="per_paper")
    stats = run_pipeline(cfg, TOPICS_PATH)
    assert stats["emailed"] == 3
    assert len(sent) == 1
    assert sent[0]["subject"].startswith("[AI Digest]")
    assert "问题" in sent[0]["body"]
    assert "GPU DiskANN Serving" in sent[0]["body"]


def test_e2e_blogs_only_when_no_focus_papers(tmp_path, monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr("src.arxiv_client.fetch_papers", lambda **kwargs: [FETCHED[3]])
    monkeypatch.setattr("src.semantic_scholar_client.fetch_papers", lambda **kwargs: [])
    monkeypatch.setattr(
        "src.blog_client.fetch_all_blogs",
        lambda *a, **k: [{
            "id": "blog-only",
            "title": "Only a blog",
            "url": "https://example.com/only",
            "summary": "hello",
            "published": "2026-08-16",
            "source": "Lab",
        }],
    )
    monkeypatch.setattr("src.emailer.send_digest_email", lambda **kwargs: sent.append(kwargs))
    monkeypatch.setattr("src.model_client.SERVER_RESTART_WAIT_S", 0)
    cfg = _write_config(tmp_path)
    stats = run_pipeline(cfg, TOPICS_PATH)
    assert stats["emailed"] == 0
    assert stats["skipped_keyword"] == 1
    assert stats.get("blogs_emailed") == 1
    assert len(sent) == 1
    assert "Only a blog" in sent[0]["body"]


def test_e2e_real_config_and_topics_load():
    from src.config import load_config
    from src.topics import load_topics

    topics = load_topics(TOPICS_PATH)
    assert [t["id"] for t in topics] == [
        "ann-retrieval-systems", "systems-memory", "agent-os",
    ]
    cfg = load_config(REPO / "config" / "config.yaml")
    assert cfg["email"]["digest_mode"] == "topic_briefing"
    assert cfg["idea_exploration"]["enabled"] is True
    assert "ann-retrieval-systems" not in str(cfg["semantic_scholar"]["queries"])
    joined = " ".join(cfg["semantic_scholar"]["queries"]).lower()
    assert "nearest neighbor" in joined
    assert "cxl" in joined
    assert "agent operating system" in joined
