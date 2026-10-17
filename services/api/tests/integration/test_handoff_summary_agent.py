"""多 Agent 阶段 1：A7 交接摘要 Agent。

失败方式：
F1 为一句摘要跑整条起草-核验流程（多次调用、主档位）。
F2 同一次转人工重复生成摘要。
F3 摘要编造记录里没有的进度（如“已到账”）仍被显示。
F4 模型失败时摘要区空白或接口报错（应显示转人工原因与触发原话）。
F5 摘要没有独立追踪，或追踪不关联原会话。
"""

import json

from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures

from app.audit.trace_models import AgentSpanRow, AgentTraceRow
from app.integrations.model_provider import ChatResult

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def _handoff(client, text="我要找人工，物流三天没动了"):
    cid = fixtures._create(client)
    fixtures._send(client, cid, text)
    client.post(f"/api/customer/conversations/{cid}/handoff", headers=CUSTOMER)
    return cid


def _provider(provider, summary, calls):
    def complete(messages, **kwargs):
        calls.append(kwargs)
        if summary is None:
            raise TimeoutError("down")
        return ChatResult(text=json.dumps({"summary": summary}, ensure_ascii=False), model="fast-fixture",
                          latency_seconds=0, is_mock=True, prompt_tokens=50, completion_tokens=20)
    provider.complete = complete


def test_summary_is_one_fast_call_reused_per_handoff(workspace):
    client, factory, provider = workspace
    cid = _handoff(client)
    calls = []
    _provider(provider, "客户反馈物流三天未更新，要求人工跟进。", calls)
    first = client.post(f"/api/support/reception/{cid}/handoff-summary", headers=SUPPORT)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["source"] == "model" and body["summary"].startswith("客户反馈")
    assert len(calls) == 1 and calls[0]["model_tier"] == "fast"
    again = client.post(f"/api/support/reception/{cid}/handoff-summary", headers=SUPPORT).json()
    assert again["summary"] == body["summary"] and len(calls) == 1
    assert client.get(f"/api/support/reception/{cid}/handoff-summary", headers=SUPPORT).json()["summary"]
    with factory() as session:
        trace = session.get(AgentTraceRow, body["traceId"])
        assert trace.graph == "post_reply" and trace.trigger_type == "handoff" and trace.conversation_id == cid
        names = [s.name for s in session.scalars(select(AgentSpanRow).where(AgentSpanRow.trace_id == trace.trace_id))]
        assert "summary" in names and "summary_check" in names


def test_fabricated_progress_falls_back_to_reason_and_quote(workspace):
    client, _, provider = workspace
    cid = _handoff(client)
    _provider(provider, "客户退款已到账，现要求人工。", [])
    body = client.post(f"/api/support/reception/{cid}/handoff-summary", headers=SUPPORT).json()
    assert body["source"] == "fallback"
    assert "已到账" not in body["summary"] and "物流三天没动了" in body["summary"]


def test_model_failure_falls_back(workspace):
    client, _, provider = workspace
    cid = _handoff(client)
    _provider(provider, None, [])
    response = client.post(f"/api/support/reception/{cid}/handoff-summary", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "fallback" and response.json()["reasonLabel"] == "客户要求人工"
