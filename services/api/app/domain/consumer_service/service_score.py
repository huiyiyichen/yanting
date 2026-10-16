"""服务乐谱数据（全景方案 2.2 / 4.9）：一次会话的双方消息、消费者情绪、触发信号、等待与断谱。

官方源事实只读；消息取官方源消息加本地运行消息。情绪按 emotion.py 规则口径。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.consumer_service.emotion import score_message
from app.domain.consumer_service.models import ServiceMessageRow, ServiceRiskAlertRow
from app.domain.consumer_service.risk_rules import message_highlights
from app.domain.enums import ServiceRiskType
from app.errors import NotFoundError
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.base import ApiModel
from app.schemas.service_desk import EvidenceHighlight

BREAK_SECONDS = 30 * 60
EMOTION = {0: "calm", 1: "dissatisfied", 2: "angry"}


class ScoreNote(ApiModel):
    message_id: str
    at: str
    role: Literal["customer", "operator", "assistant", "system"]
    body: str
    level: Literal["calm", "dissatisfied", "angry"] | None = None
    signals: list[ServiceRiskType] = Field(default_factory=list)
    highlights: list[EvidenceHighlight] = Field(default_factory=list)


class ScoreWait(ApiModel):
    from_message_id: str
    to_message_id: str | None = None
    ms: int


class ScoreBreak(ApiModel):
    after_message_id: str
    before_message_id: str
    ms: int


class ServiceScoreView(ApiModel):
    conversation_id: str
    notes: list[ScoreNote]
    waits: list[ScoreWait]
    breaks: list[ScoreBreak]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


CST = timezone(timedelta(hours=8))


def _source_time(value: datetime) -> datetime:
    """官方源时间无时区，本身就是北京时间。"""
    return value.replace(tzinfo=CST) if value.tzinfo is None else value


def service_score(session: Session, conversation_id: str) -> ServiceScoreView:
    from app.domain.consumer_service.workspace import active_batch

    batch = active_batch(session)
    rows: list[tuple[set[str], str, datetime, str, str]] = []
    if batch:
        for row in session.scalars(select(ServiceMessageRow).where(
                ServiceMessageRow.batch_id == batch, ServiceMessageRow.conversation_id == conversation_id)
                .order_by(ServiceMessageRow.sent_at, ServiceMessageRow.sequence)):
            rows.append(({row.message_id, row.source_record_id, row.record_id}, row.message_id,
                         _source_time(row.sent_at), row.sender_role, row.body or ""))
    for row in ConversationRepository(session).list_messages(conversation_id):
        rows.append(({row.message_id}, row.message_id, _utc(row.created_at), row.sender_role, row.body or ""))
    if not rows:
        raise NotFoundError("会话不存在")
    rows.sort(key=lambda item: item[2])
    by_ref: dict[str, list[ServiceRiskType]] = {}
    alert_query = select(ServiceRiskAlertRow).where(ServiceRiskAlertRow.conversation_id == conversation_id)
    if batch:
        alert_query = alert_query.where(ServiceRiskAlertRow.batch_id == batch)
    for alert in session.scalars(alert_query):
        for ref in json.loads(alert.evidence_refs_json or "[]"):
            types = by_ref.setdefault(str(ref), [])
            if alert.risk_type not in types:
                types.append(ServiceRiskType(alert.risk_type))
    notes: list[ScoreNote] = []
    for refs, message_id, at, role, body in rows:
        customer = role == "customer"
        signals = list(dict.fromkeys(t for ref in refs for t in by_ref.get(ref, [])))
        notes.append(ScoreNote(
            message_id=message_id, at=at.isoformat(),
            role=role if role in {"customer", "operator", "assistant", "system"} else "system",  # type: ignore[arg-type]
            body=body, level=EMOTION[score_message(body)] if customer and body else None,
            signals=signals if customer else [], highlights=message_highlights(body) if customer else [],
        ))
    waits: list[ScoreWait] = []
    pending: ScoreNote | None = None
    for note in notes:
        if note.role == "customer":
            pending = pending or note
        elif note.role in {"operator", "assistant"} and pending is not None:
            waits.append(ScoreWait(from_message_id=pending.message_id, to_message_id=note.message_id,
                                   ms=int((datetime.fromisoformat(note.at) - datetime.fromisoformat(pending.at)).total_seconds() * 1000)))
            pending = None
    breaks = [
        ScoreBreak(after_message_id=a.message_id, before_message_id=b.message_id,
                   ms=int((datetime.fromisoformat(b.at) - datetime.fromisoformat(a.at)).total_seconds() * 1000))
        for a, b in zip(notes, notes[1:], strict=False)
        if (datetime.fromisoformat(b.at) - datetime.fromisoformat(a.at)).total_seconds() > BREAK_SECONDS
    ]
    return ServiceScoreView(conversation_id=conversation_id, notes=notes, waits=waits, breaks=breaks)
