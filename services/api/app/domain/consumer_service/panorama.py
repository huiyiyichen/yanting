"""AI 接待全景（全景方案第 3 章）：未结束的本地会话按泳道汇总。

泳道：AI 模式 → ai；人工模式且转人工后尚无人工回复 → wait；已有人工回复或客服主动接管 → human。
官方历史会话不进入全景。步骤进度读进程内登记表（job_progress）。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.case_state.models import CaseRow, ConversationRow, MessageRow
from app.domain.consumer_service import job_progress
from app.domain.consumer_service.emotion import has_complaint_signal, score_message
from app.schemas.base import ApiModel

EMOTION = {0: "calm", 1: "dissatisfied", 2: "angry"}
MEDICAL = ("医院", "就医", "看医生", "呼吸困难", "喉咙肿", "脸肿")


class PanoramaStep(ApiModel):
    name: str
    status: Literal["pending", "active", "done", "fail", "skipped"]
    duration_ms: int = 0
    #: 并行组（同组的 Agent 并行运行，预览中缩进显示）
    group: str | None = None
    attempts: int = 1


class PanoramaRun(ApiModel):
    outcome: str | None = None
    steps: list[PanoramaStep] = Field(default_factory=list)
    #: 对应的 Agent 追踪，全景卡片可跳到模型配置页「Agent 追踪」
    trace_id: str | None = None


class PanoramaItem(ApiModel):
    conversation_id: str
    buyer_alias: str
    scene: str = ""
    product_name: str | None = None
    lane: Literal["ai", "wait", "human"]
    handler: str | None = None
    emotion_bands: list[Literal["calm", "dissatisfied", "angry"]] = Field(default_factory=list)
    high_risk: bool = False
    waiting_since: str | None = None
    handoff_reason: str | None = None
    handoff_quote: str | None = None
    ai_job: Literal["queued", "running"] | None = None
    current_run: PanoramaRun | None = None
    last_run: PanoramaRun | None = None
    last_activity_at: str
    lane_entered_at: str


class PanoramaView(ApiModel):
    items: list[PanoramaItem]
    running: int = 0
    queued: int = 0
    active_window_minutes: int = 120


def _iso(value: datetime) -> str:
    return (value.replace(tzinfo=UTC) if value.tzinfo is None else value).isoformat()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def handoff_label(reason: str, quote: str | None) -> str:
    """转人工原因按方案 3.5 的六种取值显示。"""
    text = quote or ""
    if reason == "customer_requested":
        return "客户要求人工"
    if reason == "safety_review":
        if any(term in text for term in MEDICAL):
            return "就医 · 安全转人工"
        if has_complaint_signal(text):
            return "投诉风险"
        return "情绪激烈" if score_message(text) >= 2 else "安全转人工"
    if reason in {"invalid_reply", "model_requested", "unsupported_image"}:
        return "核验未通过"
    if reason == "reply_timeout":
        return "超时"
    if reason == "operator_takeover":
        return "客服主动接管"
    from app.domain.consumer_service.auto_reception import HANDOFF_REASONS

    return HANDOFF_REASONS.get(reason, "待人工跟进")


AGENT_LABEL = {
    "safety_gate": "安全闸门", "triage": "分诊", "trajectory": "轨迹查询", "knowledge": "知识", "vision": "视觉",
    "composer": "共情起草", "program_check": "程序核验", "verifier": "核验", "output_gate": "输出闸门",
    "send_gate": "发送闸门", "rewriter": "改写", "understand": "意图情绪",
}


def _last_run_from_trace(session: Session, conversation_id: str) -> dict | None:
    """上一轮 AI 处理从落库的追踪读取，进程重启后仍在（追溯 T8）；按实际运行的 Agent 列出（8.2）。"""
    from app.audit.trace_models import AgentSpanRow, AgentTraceRow

    trace = session.scalar(select(AgentTraceRow).where(
        AgentTraceRow.conversation_id == conversation_id, AgentTraceRow.graph == "reception",
        AgentTraceRow.status != "running",
    ).order_by(AgentTraceRow.started_at.desc()).limit(1))
    if trace is None:
        return None
    steps: dict[str, dict] = {}
    for span in session.scalars(select(AgentSpanRow).where(
            AgentSpanRow.trace_id == trace.trace_id, AgentSpanRow.parent_span_id.is_(None),
            AgentSpanRow.kind != "model").order_by(AgentSpanRow.seq)):
        failed = span.status not in {"ok", "skipped"} or (
            span.kind == "decision" and "转人工" in (span.reasons_json or ""))
        status = "fail" if failed else "skipped" if span.status == "skipped" else "done"
        step = steps.get(span.name)
        if step is None:
            steps[span.name] = {"name": AGENT_LABEL.get(span.name) or span.label or span.name, "status": status,
                                "durationMs": span.duration_ms or 0, "group": span.parallel_group, "attempts": 1}
            continue
        step["durationMs"] += span.duration_ms or 0
        step["attempts"] += 1
        step["status"] = status
    return {"outcome": trace.status, "steps": list(steps.values()), "traceId": trace.trace_id}


def _run(raw: dict | None) -> PanoramaRun | None:
    if not raw:
        return None
    return PanoramaRun(outcome=raw.get("outcome"), trace_id=raw.get("traceId"), steps=[
        PanoramaStep(name=s["name"], status=s["status"], duration_ms=s["durationMs"], group=s.get("group"),
                     attempts=s.get("attempts", 1)) for s in raw["steps"]])


def panorama(session: Session, *, window_minutes: int, now: datetime | None = None) -> PanoramaView:
    from app.domain.consumer_service.auto_reception import latest_jobs
    from app.domain.consumer_service.models import ReceptionHandoffRow
    from app.domain.consumer_service.workspace import reception_snapshot

    now = now or datetime.now(UTC)
    snapshot = {item.conversation_id: item for item in reception_snapshot(session).items if item.data_source == "live"}
    live_ids = {cid for cid, item in snapshot.items()}
    closed = set(session.scalars(select(CaseRow.conversation_id).where(CaseRow.case_status == "closed")))
    handoffs = {row.conversation_id: row for row in session.scalars(select(ReceptionHandoffRow))}
    jobs = latest_jobs(session)
    messages: dict[str, list[MessageRow]] = defaultdict(list)
    for message in session.scalars(select(MessageRow).where(MessageRow.conversation_id.in_(live_ids))
                                   .order_by(MessageRow.created_at)):
        messages[message.conversation_id].append(message)
    items: list[PanoramaItem] = []
    for row in session.scalars(select(ConversationRow).where(ConversationRow.conversation_id.in_(live_ids))):
        cid = row.conversation_id
        base = snapshot[cid]
        history = messages.get(cid, [])
        if cid in closed or not history:
            continue
        last_at = _utc(history[-1].created_at)
        if window_minutes and last_at < now - timedelta(minutes=window_minutes):
            continue
        customer = [m for m in history if m.sender_role == "customer" and m.body]
        handoff = handoffs.get(cid)
        lane: Literal["ai", "wait", "human"] = "ai"
        handler = None
        lane_entered = _utc(row.created_at)
        quote = None
        if row.service_mode != "autonomous":
            since = _utc(handoff.created_at) if handoff else _utc(row.created_at)
            staff = [m for m in history if m.sender_role == "operator" and _utc(m.created_at) >= since]
            taken = handoff is not None and handoff.reason == "operator_takeover"
            lane = "human" if staff or taken else "wait"
            lane_entered = _utc(staff[0].created_at) if staff and not taken else since
            if lane == "human":
                handler = handoff.actor if handoff and handoff.actor not in {"system", "customer", "operator"} else "客服"
            before = [m for m in customer if _utc(m.created_at) <= since]
            quote = (before[-1].body if before else None)
        job = jobs.get(cid)
        ai_job = job.status if job is not None and job.status in {"queued", "running"} and lane == "ai" else None
        current = job_progress.running_for(cid) if ai_job == "running" else None
        items.append(PanoramaItem(
            conversation_id=cid, buyer_alias=base.buyer_alias, scene=base.title,
            lane=lane, handler=handler,
            emotion_bands=[EMOTION[score_message(m.body)] for m in customer[-6:]],
            high_risk=base.risk_level == "high",
            waiting_since=base.waiting_since,
            handoff_reason=handoff_label(handoff.reason, quote) if lane == "wait" and handoff else None,
            handoff_quote=quote if lane == "wait" else None,
            ai_job=ai_job, current_run=_run(current), last_run=_run(_last_run_from_trace(session, cid) or job_progress.last_for(cid)),
            last_activity_at=_iso(last_at), lane_entered_at=_iso(lane_entered),
        ))
    return PanoramaView(items=items, running=sum(i.ai_job == "running" for i in items),
                        queued=sum(i.ai_job == "queued" for i in items), active_window_minutes=window_minutes)
