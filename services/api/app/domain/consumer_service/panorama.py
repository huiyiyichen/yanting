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
    status: Literal["pending", "active", "done", "fail"]
    duration_ms: int = 0


class PanoramaRun(ApiModel):
    outcome: str | None = None
    steps: list[PanoramaStep] = Field(default_factory=list)


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


def _run(raw: dict | None) -> PanoramaRun | None:
    if not raw:
        return None
    return PanoramaRun(outcome=raw.get("outcome"), steps=[
        PanoramaStep(name=s["name"], status=s["status"], duration_ms=s["durationMs"]) for s in raw["steps"]])


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
            ai_job=ai_job, current_run=_run(current), last_run=_run(job_progress.last_for(cid)),
            last_activity_at=_iso(last_at), lane_entered_at=_iso(lane_entered),
        ))
    return PanoramaView(items=items, running=sum(i.ai_job == "running" for i in items),
                        queued=sum(i.ai_job == "queued" for i in items), active_window_minutes=window_minutes)
