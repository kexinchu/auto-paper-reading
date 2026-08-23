"""Tests for email formatting."""

from src import emailer


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


def test_format_topic_briefing_html():
    briefing = {
        "overview": "今日主线是推理 Serving。",
        "thinking": "系统优化与内存互连在本批汇合。",
        "clusters": [{
            "cluster_id": "serving-memory",
            "title": "推理 Serving 与内存",
            "topic_ids": ["llm-opt"],
            "why_grouped": "同时讨论调度与 HBM",
            "narrative": "本批工作围绕吞吐。",
            "trends": ["前缀缓存"],
            "divergences": ["离线量化"],
            "must_read": [{"paper_id": "2401.1", "why": "系统最完整"}],
            "close_reads": [{
                "paper_id": "2401.1",
                "mechanism": "按前缀命中重排队列",
                "limitation": "假设请求可预测",
                "open_question": "在线负载是否仍成立",
                "why_first": "机制最完整",
            }],
            "papers": [{"paper_id": "2401.1", "one_liner": "提出新调度"}],
        }],
    }
    summaries = [{
        "paper_id": "2401.1",
        "title": "Fast Serving",
        "published": "2026-08-17",
        "topics": [{"topic_id": "llm-opt", "relevance": 0.9}],
        "takeaways": ["提出新调度"],
    }]
    idea_briefing = {
        "thinking": "CXL 与 ANN 可组合。",
        "ideas": [{
            "idea_id": "cxl-ann",
            "title": "CXL 上的分层 ANN",
            "topic_ids": ["ann-retrieval-systems"],
            "statement": "热图在本机，冷边在 CXL。",
            "motivation": "磁盘索引没碰 CXL。",
            "gap": "没有处理 CXL 延迟抖动",
            "approach_sketch": "按访问频率迁移。",
            "experiments": ["对照 DiskANN 测 CXL 延迟下 recall"],
            "risks": ["带宽不够撑边访问"],
            "not_a_reimplementation": "不是再做磁盘索引",
            "related_papers": [{"paper_id": "2401.1", "relation": "gaps", "note": "只做磁盘"}],
            "external_related": [{"title": "DiskANN", "year": "2019", "overlap": "磁盘层次可借鉴"}],
            "potential": {"score": 0.8, "novelty": "moderate", "feasibility": "medium", "why": "硬件已到"},
            "scope": {"verdict": "just_right", "horizon": "conference", "why": "一篇系统论文"},
            "decision": "pursue",
            "decision_reason": "缺口清楚",
        }],
    }
    html = emailer.format_topic_briefing_html(
        briefing, summaries, "2026-08-17",
        stats={"total": 10, "ideas_explored": 1},
        idea_briefing=idea_briefing,
    )
    assert "今日论文脉络" in html
    assert "今日判断" in html
    assert "推理 Serving 与内存" in html
    assert "建议先读" in html
    assert "精读" in html
    assert "按前缀命中重排队列" in html
    assert "Fast Serving" in html
    assert "提出新调度" in html
    assert '<div class="section-title">问题</div>' not in html  # no per-paper 7-section cards
    assert "arxiv.org/pdf/2401.1" in html
    assert "想法探索" in html
    assert "值得跟" in html
    assert "CXL 上的分层 ANN" in html
    assert "机制缺口" in html
    assert "可做实验" in html
    assert "不是复现因为" in html
    assert "本批相关论文" in html
    assert "DiskANN" in html


def test_format_topic_briefing_html_blogs_only():
    html = emailer.format_topic_briefing_html(
        None, [], "2026-08-17",
        blog_posts=[{
            "title": "A post",
            "url": "https://example.com/p",
            "source": "OpenAI Blog",
            "published": "2026-08-16",
            "summary": "hello",
        }],
    )
    assert "Blog & Community" in html
    assert "A post" in html
