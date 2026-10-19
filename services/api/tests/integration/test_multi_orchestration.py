"""多 Agent 阶段 2+3 简化版：分诊 A1 + 路由 R1 + 并行取证 + 汇合 J1。

失败方式：
M1 multi 下没有分诊跨度，或分诊的派发结果不进追踪。
M2 纯物流问题仍然查知识（多一次检索）；跳过的 Worker 在追踪里看不到原因。
M3 商品问题没派发知识，或知识检索还在用轨迹查询的主会话（并行时 SQLite 会话冲突）。
M4 轨迹查询与知识检索没有真的并行（两者必须能同时处于运行中）。
M5 并行分支的父跨度不一致，或没有标记并行组 evidence。
M6 知识分支的来源没有并入起草的来源目录。
M7 single 模式不出现分诊跨度，仍按旧顺序执行。
"""

import json
import threading

import pytest
from tests.integration import test_reception_workspace as fixtures

from app.integrations.model_provider import ChatResult

workspace = fixtures.workspace
DRAFT = {
    "current_question": "咨询", "emotion_level": "calm", "missing_information": [],
    "next_steps": ["继续跟进"],
    "reply_suggestions": [{"style": "recommended", "body": "亲，我这边帮您看一下，您稍等哈。"}],
}


@pytest.fixture
def multi(workspace):
    client, factory, provider = workspace
    object.__setattr__(client.app.state.runtime.settings, "orchestration", "multi")
    seen = {"draft": []}

    def complete(messages, **kwargs):
        if messages[0].content.startswith("GROUNDING_REVIEW_V1"):
            return ChatResult(text=json.dumps({"supported": True, "issues": []}), model="v",
                              latency_seconds=0, is_mock=True)
        seen["draft"].append(json.loads(messages[1].content))
        return ChatResult(text=json.dumps(DRAFT, ensure_ascii=False), model="main", latency_seconds=0, is_mock=True)

    provider.complete = complete
    return client, factory, provider, seen


def _run(client, factory, provider, text, search):
    from app.domain.consumer_service.grounded_workflow import run_grounded_workflow

    cid = fixtures._create(client)
    fixtures._send(client, cid, text)
    with factory() as session:
        result = run_grounded_workflow(
            session, provider, cid, automatic=False, knowledge_search=search,
            settings=client.app.state.runtime.settings,
        )
        return result, session


def _spans(result):
    return {span.name: span for span in result["trace"].spans if span.kind != "model_call"}


def test_logistics_question_skips_knowledge_with_reason(multi):
    client, factory, provider, _ = multi
    calls = []
    result, _ = _run(client, factory, provider, "我的快递怎么还没到", lambda q, **k: calls.append(q) or ([], "not_found"))
    spans = _spans(result)
    assert "triage" in spans  # M1
    route = result["route"].dump()
    assert route["workers"] == ["trajectory"] and route["knowledge"] is False
    assert calls == []  # M2
    assert spans["knowledge"].status == "skipped" and "分诊未派发知识" in spans["knowledge"].reasons[0]
    assert spans["trajectory"].parallel_group == "evidence"
    assert result["knowledge_status"] == "skipped"
    assert any("派发" in str(r) for r in spans["triage"].reasons)


def test_product_question_runs_trajectory_and_knowledge_in_parallel(multi, monkeypatch):
    from app.domain.consumer_service import grounded_workflow

    client, factory, provider, seen = multi
    both_running = threading.Barrier(2, timeout=5)
    original_collect = grounded_workflow.collect_sources

    def collect_sources(*args, **kwargs):
        both_running.wait()  # 只有知识分支同时在跑才能通过（M4）
        return original_collect(*args, **kwargs)

    monkeypatch.setattr(grounded_workflow, "collect_sources", collect_sources)
    sessions = []
    evidence = [{
        "chunk_id": "k1", "document_id": "doc1", "document_title": "面霜使用说明", "document_version": "1",
        "quoted_excerpt": "敏感肌可先在耳后试用", "source_text": "敏感肌可先在耳后试用",
        "document_metadata": {}, "applicability": {},
    }]

    def search(query, *, session=None):
        sessions.append(session)
        both_running.wait()
        return evidence, "sufficient"

    result, main_session = _run(client, factory, provider, "这款面霜敏感肌能用吗", search)
    spans = _spans(result)
    assert result["route"].knowledge is True  # M3
    assert sessions and sessions[0] is not None and sessions[0] is not main_session  # M3
    trajectory, knowledge = spans["trajectory"], spans["knowledge"]
    assert trajectory.parent_span_id == knowledge.parent_span_id  # M5
    assert {trajectory.parallel_group, knowledge.parallel_group} == {"evidence"}
    assert trajectory.started_at < knowledge.ended_at and knowledge.started_at < trajectory.ended_at  # M4
    catalog = {s["sourceId"] for s in seen["draft"][-1]["sourceCatalog"]}
    assert "knowledge:k1" in catalog  # M6
    assert any(s.source_id == "knowledge:k1" for s in result["sources"])


def test_single_mode_has_no_triage(workspace):
    from app.domain.consumer_service.grounded_workflow import run_grounded_workflow

    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "我的快递怎么还没到")
    calls = []
    with factory() as session:
        result = run_grounded_workflow(
            session, provider, cid, automatic=False,
            knowledge_search=lambda q: calls.append(q) or ([], "not_found"),
            settings=client.app.state.runtime.settings,
        )
    names = [span.name for span in result["trace"].spans if span.kind != "model_call"]
    assert "triage" not in names  # M7
    assert names.index("trajectory") < names.index("knowledge") < names.index("composer")
    assert len(calls) == 1
