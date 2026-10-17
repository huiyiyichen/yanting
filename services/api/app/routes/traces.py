"""Agent 追踪查询与导出（多 Agent 设计 7.5、8.3）。只读；仅 support 角色。"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.audit.trace_models import AgentArtifactRow, AgentSpanRow, AgentTraceRow, ReplyCitationRow
from app.deps import get_session, require_support
from app.errors import NotFoundError
from app.routes.commit import CommitBeforeResponseRoute
from app.schemas.conversation import ApiModel

router = APIRouter(prefix="/api/platform", tags=["platform"], route_class=CommitBeforeResponseRoute)


class TraceSummaryView(ApiModel):
    trace_id: str
    graph: str
    trigger_type: str
    conversation_id: str | None = None
    buyer_alias: str | None = None
    status: str
    orchestration: str
    started_at: str
    ended_at: str | None = None
    totals: dict[str, Any]
    #: 迷你时序条：各 Agent/节点耗时（毫秒），按执行顺序
    lanes: list[dict[str, Any]]


class TraceSpanView(ApiModel):
    span_id: str
    parent_span_id: str | None = None
    seq: int
    kind: str
    name: str
    label: str
    attempt: int
    parallel_group: str | None = None
    status: str
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = None
    tier: str | None = None
    model_requested: str | None = None
    model_returned: str | None = None
    is_mock: bool | None = None
    prompt_code: str | None = None
    prompt_revision: str | None = None
    prompt_sha256: str | None = None
    contract_version: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_tokens: int | None = None
    finish_reason: str | None = None
    input_artifact: str | None = None
    output_artifact: str | None = None
    reasons: list[Any]
    error_code: str | None = None
    error_detail: str | None = None


class TraceCitationView(ApiModel):
    message_id: str | None = None
    reply_style: str
    segment_index: int
    segment_text: str
    source_id: str
    source_record_id: str | None = None
    sheet_name: str | None = None
    row_number: int | None = None
    verdict: str


class TraceDetailView(TraceSummaryView):
    trigger_message_id: str | None = None
    job_id: str | None = None
    outcome_message_id: str | None = None
    versions: dict[str, Any]
    spans: list[TraceSpanView]
    citations: list[TraceCitationView]


class TraceListView(ApiModel):
    items: list[TraceSummaryView]
    total: int


class SourceRecordView(ApiModel):
    record_id: str
    sheet_name: str
    row_number: int
    row_sha256: str
    values: dict[str, Any]


class ArtifactView(ApiModel):
    sha256: str
    kind: str
    bytes: int
    content: Any = None


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _aliases(session, conversation_ids: set[str]) -> dict[str, str]:
    from app.domain.case_state.models import ConversationRow
    from app.domain.consumer_service.models import ServiceConversationRow

    if not conversation_ids:
        return {}
    names = {row.conversation_id: row.buyer_alias for row in session.scalars(
        select(ServiceConversationRow).where(ServiceConversationRow.conversation_id.in_(conversation_ids)))
        if row.buyer_alias}
    for row in session.scalars(select(ConversationRow).where(ConversationRow.conversation_id.in_(conversation_ids))):
        alias = getattr(row, "buyer_alias", None) or getattr(row, "title", None)
        if alias and row.conversation_id not in names:
            names[row.conversation_id] = alias
    return names


def _lanes(spans: list[AgentSpanRow]) -> list[dict[str, Any]]:
    return [{"name": s.name, "label": s.label or s.name, "kind": s.kind, "status": s.status,
             "durationMs": s.duration_ms or 0}
            for s in spans if s.kind != "model_call" and s.parent_span_id is None]


def _summary(row: AgentTraceRow, spans: list[AgentSpanRow], alias: str | None) -> dict[str, Any]:
    return {
        "trace_id": row.trace_id, "graph": row.graph, "trigger_type": row.trigger_type,
        "conversation_id": row.conversation_id, "buyer_alias": alias, "status": row.status,
        "orchestration": row.orchestration, "started_at": _iso(row.started_at), "ended_at": _iso(row.ended_at),
        "totals": json.loads(row.totals_json or "{}"), "lanes": _lanes(spans),
    }


@router.get("/traces", response_model=TraceListView)
def list_traces(
    conversation_id: str | None = Query(default=None, alias="conversationId"),
    status: str | None = None,
    graph: str | None = None,
    has_repair: bool = Query(default=False, alias="hasRepair"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Any = Depends(get_session),
    _role=Depends(require_support),
):
    query = select(AgentTraceRow)
    if conversation_id:
        query = query.where(AgentTraceRow.conversation_id == conversation_id)
    if status:
        query = query.where(AgentTraceRow.status == status)
    if graph:
        query = query.where(AgentTraceRow.graph == graph)
    if has_repair:
        repaired = select(AgentSpanRow.trace_id).where(AgentSpanRow.attempt > 1)
        query = query.where(AgentTraceRow.trace_id.in_(repaired))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(session.scalars(query.order_by(AgentTraceRow.started_at.desc()).limit(limit).offset(offset)))
    ids = [row.trace_id for row in rows]
    spans: dict[str, list[AgentSpanRow]] = {}
    for span in session.scalars(select(AgentSpanRow).where(AgentSpanRow.trace_id.in_(ids)).order_by(AgentSpanRow.seq)):
        spans.setdefault(span.trace_id, []).append(span)
    aliases = _aliases(session, {row.conversation_id for row in rows if row.conversation_id})
    return TraceListView(total=total, items=[
        TraceSummaryView(**_summary(row, spans.get(row.trace_id, []), aliases.get(row.conversation_id or "")))
        for row in rows])


def _detail(session, trace_id: str) -> TraceDetailView:
    from app.domain.consumer_service.models import SourceRecordRow

    row = session.get(AgentTraceRow, trace_id)
    if row is None:
        raise NotFoundError("追踪不存在")
    spans = list(session.scalars(select(AgentSpanRow).where(AgentSpanRow.trace_id == trace_id).order_by(AgentSpanRow.seq)))
    citations = list(session.scalars(select(ReplyCitationRow).where(ReplyCitationRow.trace_id == trace_id)
                                     .order_by(ReplyCitationRow.reply_style, ReplyCitationRow.segment_index)))
    record_ids = {c.source_record_id for c in citations if c.source_record_id}
    records = {r.record_id: r for r in session.scalars(
        select(SourceRecordRow).where(SourceRecordRow.record_id.in_(record_ids)))} if record_ids else {}
    alias = _aliases(session, {row.conversation_id} if row.conversation_id else set()).get(row.conversation_id or "")
    return TraceDetailView(
        **_summary(row, spans, alias), trigger_message_id=row.trigger_message_id, job_id=row.job_id,
        outcome_message_id=row.outcome_message_id, versions=json.loads(row.versions_json or "{}"),
        spans=[TraceSpanView(
            span_id=s.span_id, parent_span_id=s.parent_span_id, seq=s.seq, kind=s.kind, name=s.name,
            label=s.label, attempt=s.attempt, parallel_group=s.parallel_group, status=s.status,
            started_at=_iso(s.started_at), ended_at=_iso(s.ended_at), duration_ms=s.duration_ms,
            tier=s.tier, model_requested=s.model_requested, model_returned=s.model_returned, is_mock=s.is_mock,
            prompt_code=s.prompt_code, prompt_revision=s.prompt_revision, prompt_sha256=s.prompt_sha256,
            contract_version=s.contract_version, prompt_tokens=s.prompt_tokens,
            completion_tokens=s.completion_tokens, cached_tokens=s.cached_tokens, finish_reason=s.finish_reason,
            input_artifact=s.input_artifact, output_artifact=s.output_artifact,
            reasons=json.loads(s.reasons_json or "[]"), error_code=s.error_code, error_detail=s.error_detail,
        ) for s in spans],
        citations=[TraceCitationView(
            message_id=c.message_id, reply_style=c.reply_style, segment_index=c.segment_index,
            segment_text=c.segment_text, source_id=c.source_id, source_record_id=c.source_record_id,
            sheet_name=records[c.source_record_id].sheet_name if c.source_record_id in records else None,
            row_number=records[c.source_record_id].row_number if c.source_record_id in records else None,
            verdict=c.verdict,
        ) for c in citations],
    )


@router.get("/traces/{trace_id}", response_model=TraceDetailView)
def trace_detail(trace_id: str, session: Any = Depends(get_session), _role=Depends(require_support)):
    return _detail(session, trace_id)


@router.get("/traces/{trace_id}/export")
def export_trace(trace_id: str, session: Any = Depends(get_session), _role=Depends(require_support)):
    """追踪、跨度、引用、版本与全部制品打成一个 JSON 包（评测与答辩证据）。"""
    detail = _detail(session, trace_id).dump()
    digests = {d for s in detail["spans"] for d in (s.get("inputArtifact"), s.get("outputArtifact")) if d}
    detail["artifacts"] = [
        {"sha256": a.sha256, "kind": a.kind, "bytes": a.bytes, "content": a.content}
        for a in session.scalars(select(AgentArtifactRow).where(AgentArtifactRow.sha256.in_(digests)))
    ] if digests else []
    return detail


@router.get("/trace-artifacts/{sha256}", response_model=ArtifactView)
def trace_artifact(sha256: str, session: Any = Depends(get_session), _role=Depends(require_support)):
    row = session.get(AgentArtifactRow, sha256)
    if row is None:
        raise NotFoundError("制品不存在或已过期")
    content: Any = row.content
    if content is not None:
        with contextlib.suppress(ValueError):
            content = json.loads(content)
    return ArtifactView(sha256=row.sha256, kind=row.kind, bytes=row.bytes, content=content)


@router.get("/source-records/{record_id}", response_model=SourceRecordView)
def source_record(record_id: str, session: Any = Depends(get_session), _role=Depends(require_support)):
    """官方 Excel 原始行：工作表名、行号、行哈希与原始字段（证明内容未被改写）。"""
    from app.domain.consumer_service.models import SourceRecordRow

    row = session.get(SourceRecordRow, record_id)
    if row is None:
        raise NotFoundError("官方记录不存在")
    return SourceRecordView(record_id=row.record_id, sheet_name=row.sheet_name, row_number=row.row_number,
                            row_sha256=row.row_sha256, values=json.loads(row.values_json or "{}"))
