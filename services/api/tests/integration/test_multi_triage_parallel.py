"""多 Agent 阶段 2+3 简化版：分诊 Leader 派发 + 轨迹/知识/视觉并行取证。

失败方式：
P1 multi 下没有分诊跨度，或分诊决定没写进追踪（看不出派了谁、为什么）。
P2 纯物流问题仍调用知识检索（分诊没有省下调用）；跳过的知识节点没有写明原因。
P3 商品问题没派发知识，或知识分支和轨迹查询共用主会话。
P4 轨迹查询与知识检索实际上仍是先后执行（时间上不重叠）。
P5 并行分支的父跨度互相嵌套，或没有标并行组。
P6 分诊出故障时回复失败，而不是按保守路由全部派发。
P7 single 模式行为改变（出现分诊跨度、知识先后执行之外的路径）。
"""

import json
import threading

import pytest
from tests.integration import test_reception_workspace as fixtures

from app.config import get_settings
from app.integrations.model_provider import ChatResult

workspace = fixtures.workspace
DRAFT = {
    "current_question": "查询订单物流", "emotion_level": "calm", "missing_information": ["订单号"],
    "next_steps": ["核对订单"], "intent": "logistics",
    "reply_suggestions": [{"style": "recommended", "body": "我来核对这笔订单，方便提供订单号吗？"}],
}


def _provider(provider):
    def complete(messages, **kwargs):
        if messages[0].content.startswith("GROUNDING_REVIEW_V1"):
            value = {"supported": True, "issues": []}
        else:
            value = DRAFT
        return ChatResult(text=json.dumps(value, ensure_ascii=False), model="fixture", latency_seconds=0,
                          is_mock=True, prompt_tokens=10, completion_tokens=5)
    provider.complete = complete


def _run(factory, provider, cid, search, orchestration="multi"):
    from app.audit import tracer
    from app.domain.consumer_service.grounded_workflow import run_grounded_workflow

    settings = get_settings().model_copy(update={"orchestration": orchestration})
    with factory() as session, tracer.use(None):
        return run_grounded_workflow(session, provider, cid, automatic=False, knowledge_search=search,
                                     settings=settings)


def _spans(result):
    return {span.name: span for span in result["trace"].spans if span.kind != "model_call"}


def test_logistics_question_skips_knowledge_with_reason(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "我的快递怎么还没到")
    _provider(provider)
    searched = []

    result = _run(factory, provider, cid, lambda query, session=None: searched.append(query) or ([], "not_found"))

    spans = _spans(result)
    assert "triage" in spans  # P1
    route = result["route"]
    assert route.workers() == ["trajectory"] and route.intent_hint == "logistics"
    summary = next(r["summary"] for r in spans["triage"].reasons if isinstance(r, dict) and "summary" in r)
    assert summary.startswith("派发 轨迹查询") and "物流" in summary
    assert spans["triage"].extra.get("output_artifact")  # 路由决定可在检查器里展开
    assert searched == []  # P2
    assert spans["knowledge"].status == "skipped" and "分诊未派发知识" in spans["knowledge"].reasons[0]
    assert result["knowledge_status"] == "skipped"
    assert result["draft"] is not None


def test_product_question_runs_trajectory_and_knowledge_in_parallel(workspace, monkeypatch):
    from app.domain.consumer_service import grounded_workflow

    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "这款面霜敏感肌能用吗")
    _provider(provider)
    knowledge_started = threading.Event()
    overlapped = {}
    original_risk = grounded_workflow._active_risk_level

    def risk_waits_for_knowledge(session, conversation_id):
        # 轨迹查询里等知识分支开始；若两者先后执行，这里会一直等到超时
        overlapped["value"] = knowledge_started.wait(timeout=5)
        return original_risk(session, conversation_id)

    monkeypatch.setattr(grounded_workflow, "_active_risk_level", risk_waits_for_knowledge)
    seen_sessions = []

    def search(query, session=None):
        seen_sessions.append(session)
        knowledge_started.set()
        return [], "not_found"

    with factory() as main_session:
        result = _run(factory, provider, cid, search)
        assert all(s is not None and s is not main_session for s in seen_sessions)  # P3

    assert result["route"].knowledge is True  # P3
    assert len(seen_sessions) == 1
    assert overlapped["value"] is True  # P4
    spans = _spans(result)
    trajectory, knowledge, triage = spans["trajectory"], spans["knowledge"], spans["triage"]
    assert trajectory.parent_span_id == knowledge.parent_span_id == triage.parent_span_id  # P5
    assert trajectory.parallel_group == knowledge.parallel_group == "evidence"
    assert trajectory.started_at < knowledge.ended_at and knowledge.started_at < trajectory.ended_at  # P4


def test_triage_failure_falls_back_to_conservative_route(workspace, monkeypatch):
    from app.domain.consumer_service import grounded_workflow

    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "我的快递怎么还没到")
    _provider(provider)

    def broken(*args, **kwargs):
        raise RuntimeError("triage down")

    monkeypatch.setattr(grounded_workflow, "triage", broken)
    searched = []
    result = _run(factory, provider, cid, lambda query, session=None: searched.append(query) or ([], "not_found"))

    assert result["route"].conservative is True  # P6
    assert result["route"].knowledge is True and len(searched) == 1
    assert result["draft"] is not None


@pytest.mark.parametrize("orchestration", ["single"])
def test_single_mode_has_no_triage_and_runs_sequentially(workspace, orchestration):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "我的快递怎么还没到")
    _provider(provider)
    searched = []
    result = _run(factory, provider, cid, lambda query: searched.append(query) or ([], "not_found"),
                  orchestration=orchestration)

    spans = _spans(result)
    assert "triage" not in spans and "route" not in result  # P7
    assert len(searched) == 1
    assert spans["trajectory"].parallel_group is None
    assert spans["trajectory"].ended_at <= spans["knowledge"].started_at
