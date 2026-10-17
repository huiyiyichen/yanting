"""多 Agent 阶段 0：追踪地基。

失败方式：
F1 生成回复后没有追踪，或跨度缺少节点（轨迹、知识、起草、程序校验、输出确认）。
F2 追踪的调用数与 model_call 跨度数不一致；失败或超时的模型调用没有跨度。
F3 自动发送的消息查不到追踪；引用没有关联到发出的消息。
F4 订单/源工单来源不带官方记录号，引用追不到工作表和行；或官方记录号被塞进给模型的来源目录。
F5 记录器异常导致接待失败。
F6 导出包缺少送给模型的输入与模型原始输出。
"""

import json

from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures
from tests.integration.test_auto_reception import jobs

from app.audit import tracer
from app.audit.trace_models import AgentSpanRow, AgentTraceRow, ReplyCitationRow
from app.domain.consumer_service.auto_reception import process_job
from app.domain.consumer_service.grounding import collect_sources
from app.domain.consumer_service.models import ServiceOrderRow, SourceRecordRow
from app.errors import ProviderTimeout

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT


def _generate(client):
    cid = fixtures._create(client)
    fixtures._send(client, cid, "查询订单物流")
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    return cid, response.json()


def test_draft_generation_writes_a_complete_trace(workspace):
    client, _factory, _ = workspace
    cid, view = _generate(client)
    trace_id = view["modelUsage"]["traceId"]
    detail = client.get(f"/api/platform/traces/{trace_id}", headers=SUPPORT).json()
    names = [s["name"] for s in detail["spans"] if s["kind"] != "model_call"]
    for name in ("trajectory", "knowledge", "composer", "program_check", "output_gate"):
        assert name in names
    calls = [s for s in detail["spans"] if s["kind"] == "model_call"]
    assert detail["totals"]["calls"] == len(calls) == view["modelUsage"]["calls"]
    assert all(c["parentSpanId"] for c in calls)
    assert all(c["inputArtifact"] and c["outputArtifact"] for c in calls)
    assert detail["status"] == "draft" and detail["conversationId"] == cid
    listed = client.get(f"/api/platform/traces?conversationId={cid}", headers=SUPPORT).json()
    assert listed["items"][0]["traceId"] == trace_id and listed["items"][0]["lanes"]
    exported = client.get(f"/api/platform/traces/{trace_id}/export", headers=SUPPORT).json()
    kinds = {a["kind"] for a in exported["artifacts"]}
    assert {"input_payload", "model_output"} <= kinds


def test_failed_model_call_is_a_span(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "查询订单物流")

    def boom(messages, **kwargs):
        raise ProviderTimeout("provider down")

    provider.complete = boom
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code >= 400
    with factory() as session:
        trace = session.scalar(select(AgentTraceRow).where(AgentTraceRow.conversation_id == cid))
        assert trace is not None and trace.status == "failed"
        failed = session.scalars(select(AgentSpanRow).where(
            AgentSpanRow.trace_id == trace.trace_id, AgentSpanRow.kind == "model_call")).all()
        assert len(failed) == 1 and failed[0].status != "ok" and failed[0].error_code


def test_auto_sent_message_links_to_trace_and_citations(workspace):
    client, factory, _ = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "咨询物流")
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    job = jobs(factory, cid)[0]
    assert job.status == "sent"
    with factory() as session:
        trace = session.scalar(select(AgentTraceRow).where(AgentTraceRow.job_id == job.job_id))
        assert trace.status == "sent" and trace.outcome_message_id == job.reply_message_id
        names = [s.name for s in session.scalars(select(AgentSpanRow).where(AgentSpanRow.trace_id == trace.trace_id))]
        assert names[0] == "safety_gate" and names[-1] == "send_gate"
        cites = session.scalars(select(ReplyCitationRow).where(ReplyCitationRow.trace_id == trace.trace_id)).all()
        assert all(c.message_id == job.reply_message_id for c in cites if c.reply_style == "recommended")


def test_official_sources_carry_record_ids_but_prompts_do_not(workspace):
    client, factory, _ = workspace
    with factory() as session:
        order = session.scalars(select(ServiceOrderRow)).first()
        sources = collect_sources(session, order.conversation_id)
        order_source = next(s for s in sources if s.kind == "order")
        assert order_source.source_record_id
        assert session.get(SourceRecordRow, order_source.source_record_id) is not None
        assert "sourceRecordId" not in order_source.prompt_dump()
    record = client.get(f"/api/platform/source-records/{order_source.source_record_id}", headers=SUPPORT).json()
    assert record["sheetName"] and record["rowNumber"] > 0 and record["values"]


def test_recorder_failure_does_not_break_generation(workspace, monkeypatch):
    client, _, _ = workspace

    def broken(self):
        raise RuntimeError("recorder broken")

    monkeypatch.setattr(tracer.Trace, "totals", broken)
    before = tracer.recorder_errors
    _cid, view = _generate(client)
    assert view["replySuggestions"]
    assert tracer.recorder_errors > before
    json.dumps(view)


def test_integrity_check_passes_after_draft_and_auto_reply(workspace):
    """F7 完整性检查（设计 7.6）任一项低于 100%。"""
    from app.audit.trace_integrity import check

    client, factory, _ = workspace
    _generate(client)
    cid = fixtures._create(client)
    fixtures._send(client, cid, "咨询物流")
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    with factory() as session:
        report = check(session)
    assert report["allPassed"], report
    assert next(r for r in report["checks"] if r["check"] == "消息有来源")["total"] >= 1
