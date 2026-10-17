"""追踪完整性检查（多 Agent 设计 7.6）：每项给出分子/分母，验收要求全部 100%。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

OFFICIAL_KINDS = ("order:", "work_order:")


def check(session: Session) -> dict[str, Any]:
    from app.audit.trace_models import AgentSpanRow, AgentTraceRow, ReplyCitationRow
    from app.domain.case_state.models import MessageRow
    from app.domain.consumer_service.models import AutoReplyJobRow, SourceRecordRow

    traces = list(session.scalars(select(AgentTraceRow)))
    spans = list(session.scalars(select(AgentSpanRow)))
    span_ids = {s.span_id for s in spans}
    by_trace: dict[str, list[AgentSpanRow]] = {}
    for span in spans:
        by_trace.setdefault(span.trace_id, []).append(span)
    outcomes = {t.outcome_message_id for t in traces if t.outcome_message_id}
    auto_messages = list(session.scalars(select(MessageRow).where(
        MessageRow.sender_role == "assistant", MessageRow.client_message_key.like("auto:%"))))
    citations = list(session.scalars(select(ReplyCitationRow)))
    records = set(session.scalars(select(SourceRecordRow.record_id)))
    jobs = {j.job_id: j for j in session.scalars(select(AutoReplyJobRow))}

    def item(name: str, ok: int, total: int, failures: list[str]) -> dict[str, Any]:
        return {"check": name, "passed": ok, "total": total,
                "rate": 1.0 if total == 0 else round(ok / total, 4), "failures": failures[:20]}

    official = [c for c in citations if c.source_id.startswith(OFFICIAL_KINDS)]
    calls_ok = [t for t in traces if json.loads(t.totals_json or "{}").get("calls", 0)
                == sum(s.kind == "model_call" for s in by_trace.get(t.trace_id, []))]
    model_spans = [s for s in spans if s.kind == "model_call"]
    job_traces = [t for t in traces if t.job_id and t.job_id in jobs]
    consistent = [t for t in job_traces if t.status == jobs[t.job_id].status
                  or (t.status == "running" and jobs[t.job_id].status in {"queued", "running"})
                  or (t.status == "interrupted" and jobs[t.job_id].status in {"handoff", "superseded"})]
    results = [
        item("消息有来源", sum(m.message_id in outcomes for m in auto_messages), len(auto_messages),
             [m.message_id for m in auto_messages if m.message_id not in outcomes]),
        item("官方引用可解析", sum(c.source_record_id in records for c in official), len(official),
             [c.citation_id for c in official if c.source_record_id not in records]),
        item("调用有记录", len(calls_ok), len(traces),
             [t.trace_id for t in traces if t not in calls_ok]),
        item("版本齐全", sum(bool(s.contract_version) for s in model_spans), len(model_spans),
             [s.span_id for s in model_spans if not s.contract_version]),
        item("状态一致", len(consistent), len(job_traces),
             [t.trace_id for t in job_traces if t not in consistent]),
        item("无孤儿跨度", sum(s.parent_span_id is None or s.parent_span_id in span_ids for s in spans), len(spans),
             [s.span_id for s in spans if s.parent_span_id and s.parent_span_id not in span_ids]),
    ]
    return {"checks": results, "allPassed": all(r["rate"] == 1.0 for r in results)}
