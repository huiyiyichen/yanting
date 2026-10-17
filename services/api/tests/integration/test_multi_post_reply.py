"""多 Agent 阶段 1（orchestration=multi）：起草契约瘦身 + A6 记忆 Agent。

失败方式：
F1 起草仍输出已移出的字段（service_summary/memory/service_breakpoints）被静默丢弃，而非报契约错误进修复轮。
F2 multi 下起草提示词仍要求输出记忆或服务断点。
F3 记忆在回复之前读取/写入，或由起草输出覆盖成空。
F4 记忆 Agent 写入不带逐字原文的条目；客服承诺被记为已尝试。
F5 记忆 Agent 失败时旧记忆被清空，或建议生成失败。
F6 记忆没有独立追踪，或追踪不关联原会话。
F7 single 模式行为改变（起草仍可带摘要、记忆）。
F8 转人工后没有触发风险哨兵；同一会话 10 分钟内重复触发；哨兵失败影响交接摘要。
"""

import json

import pytest
from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures

from app.audit.trace_models import AgentSpanRow, AgentTraceRow
from app.integrations.model_provider import ChatResult

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT
DRAFT = {
    "current_question": "查询订单物流", "emotion_level": "calm", "missing_information": ["订单号"],
    "next_steps": ["核对订单"],
    "reply_suggestions": [{"style": "recommended", "body": "我来核对这笔订单，方便提供订单号吗？"}],
}


@pytest.fixture
def multi(workspace):
    client, factory, provider = workspace
    object.__setattr__(client.app.state.runtime.settings, "orchestration", "multi")
    return client, factory, provider


def _route(provider, *, draft_outputs, memory=None, memory_error=False):
    seen = {"draft": [], "memory": []}
    original = provider.complete

    def complete(messages, **kwargs):
        system = messages[0].content
        if system.startswith("YT_MEMORY_V1"):
            seen["memory"].append(messages)
            if memory_error:
                raise TimeoutError("down")
            return ChatResult(text=json.dumps({"memory": memory or []}, ensure_ascii=False), model="fast",
                              latency_seconds=0, is_mock=True)
        if system.startswith("GROUNDING_REVIEW_V1"):
            return original(messages, **kwargs)
        seen["draft"].append(messages)
        text = draft_outputs[min(len(seen["draft"]) - 1, len(draft_outputs) - 1)]
        return ChatResult(text=json.dumps(text, ensure_ascii=False), model="main", latency_seconds=0, is_mock=True)

    provider.complete = complete
    return seen


def _start(client, text="订单物流怎么还没到，我很着急"):
    cid = fixtures._create(client)
    fixtures._send(client, cid, text)
    return cid


def _customer_source(client, cid):
    rows = client.get(f"/api/customer/conversations/{cid}/messages", headers=fixtures.CUSTOMER).json()
    first = next(r for r in rows if r["senderRole"] == "customer")
    return {"sourceId": f"message:{cid}:{first['messageId']}"}


def test_moved_fields_are_contract_errors_and_scope_is_in_prompt(multi):
    client, _, provider = multi
    cid = _start(client)
    seen = _route(provider, draft_outputs=[{**DRAFT, "service_summary": "消费者询问物流。"}, DRAFT])
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert len(seen["draft"]) == 2  # F1 进修复轮
    repair = json.loads(seen["draft"][1][1].content)
    assert any("service_summary" in issue for issue in repair.get("repairIssues", []))
    system = seen["draft"][0][0].content
    assert "COMPOSER_SCOPE_V1" in system and "service_breakpoints，最多3项" not in system  # F2
    assert "memorySourceCatalog" not in seen["draft"][0][-1].content


def test_memory_agent_runs_after_reply_and_keeps_only_grounded_items(multi):
    client, factory, provider = multi
    cid = _start(client)
    _route(provider, draft_outputs=[DRAFT], memory=[])
    client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    source = _customer_source(client, cid)
    seen = _route(provider, draft_outputs=[DRAFT], memory=[
        {"category": "concern", "source_ref": source["sourceId"], "quote": "我很着急", "label": "着急"},
        {"category": "attempted", "source_ref": source["sourceId"], "quote": "编造的内容", "label": "x"},
    ])
    fixtures._send(client, cid, "还是没到", key="customer-2")
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert len(seen["memory"]) == 1
    memory = client.get(f"/api/support/reception/{cid}/memory", headers=SUPPORT).json()
    assert [(i["category"], i["quote"]) for i in memory["items"]] == [("concern", "我很着急")]  # F4
    with factory() as session:
        trace = session.scalar(select(AgentTraceRow).where(
            AgentTraceRow.conversation_id == cid, AgentTraceRow.trigger_type == "memory"
        ).order_by(AgentTraceRow.started_at.desc()))
        assert trace.graph == "post_reply" and trace.orchestration == "multi"  # F6
        spans = session.scalars(select(AgentSpanRow).where(AgentSpanRow.trace_id == trace.trace_id)).all()
        check = next(s for s in spans if s.name == "memory_check")
        assert check.status == "failed" and "逐字原文" in check.reasons_json


def test_memory_failure_keeps_previous_memory(multi):
    client, _, provider = multi
    cid = _start(client)
    source = _customer_source(client, cid)
    _route(provider, draft_outputs=[DRAFT], memory=[
        {"category": "concern", "source_ref": source["sourceId"], "quote": "我很着急", "label": "着急"}])
    client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    fixtures._send(client, cid, "还是没到", key="customer-2")
    _route(provider, draft_outputs=[DRAFT], memory_error=True)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text  # F5
    memory = client.get(f"/api/support/reception/{cid}/memory", headers=SUPPORT).json()
    assert [i["quote"] for i in memory["items"]] == ["我很着急"]


def test_single_mode_unchanged(workspace):
    client, _, provider = workspace
    cid = _start(client)
    seen = _route(provider, draft_outputs=[{**DRAFT, "service_summary": "消费者询问物流。"}])
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert len(seen["draft"]) == 1 and not seen["memory"]  # F7
    assert response.json()["serviceSummary"] == "消费者询问物流。"


def test_handoff_triggers_sentinel_once_per_window(multi):
    client, factory, _ = multi
    cid = _start(client, "我要找人工")
    client.post(f"/api/customer/conversations/{cid}/handoff", headers=fixtures.CUSTOMER)
    for _ in range(2):
        response = client.post(f"/api/support/reception/{cid}/handoff-summary", headers=SUPPORT)
        assert response.status_code == 200, response.text
    with factory() as session:
        sentinels = session.scalars(select(AgentTraceRow).where(
            AgentTraceRow.conversation_id == cid, AgentTraceRow.trigger_type == "sentinel:handoff")).all()
        assert len(sentinels) == 1 and sentinels[0].graph == "post_reply"
