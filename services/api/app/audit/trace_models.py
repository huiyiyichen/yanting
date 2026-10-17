"""Agent 追踪四张表（多 Agent 设计 7.2）：追踪、跨度、制品、回复引用。

追踪只追加，不改写业务表；业务失败时也要能看到失败前的步骤。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.case_state.models import Base


def _now() -> datetime:
    return datetime.now(UTC)


class AgentTraceRow(Base):
    __tablename__ = "agent_trace"

    trace_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    graph: Mapped[str] = mapped_column(String(24))
    trigger_type: Mapped[str] = mapped_column(String(32))
    conversation_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    trigger_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    mode_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    message_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orchestration: Mapped[str] = mapped_column(String(16), default="single")
    versions_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(24), default="running")
    outcome_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retry_of: Mapped[str | None] = mapped_column(String(40), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    totals_json: Mapped[str] = mapped_column(Text, default="{}")


class AgentSpanRow(Base):
    __tablename__ = "agent_span"

    span_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(40), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(64), default="")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    parallel_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model_requested: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_returned: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_mock: Mapped[bool | None] = mapped_column(nullable=True)
    prompt_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contract_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_artifact: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_artifact: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)


class AgentArtifactRow(Base):
    __tablename__ = "agent_artifact"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReplyCitationRow(Base):
    __tablename__ = "reply_citation"

    citation_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    message_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(40), index=True)
    reply_style: Mapped[str] = mapped_column(String(24), default="recommended")
    segment_index: Mapped[int] = mapped_column(Integer, default=0)
    segment_text: Mapped[str] = mapped_column(Text, default="")
    source_id: Mapped[str] = mapped_column(String(200), index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    verdict: Mapped[str] = mapped_column(String(24), default="verified")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
