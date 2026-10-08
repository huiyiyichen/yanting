"""Immutable imported facts. AI results and mutable chat never overwrite these tables."""

from datetime import UTC, datetime

from sqlalchemy import (
    DDL,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.case_state.models import Base


class ImportBatchRow(Base):
    __tablename__ = "service_import_batch"
    __table_args__ = (UniqueConstraint("source_sha256", "mapping_version"),)

    batch_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String(64))
    mapping_version: Mapped[str] = mapped_column(String(64))
    source_name: Mapped[str] = mapped_column(String(300))
    snapshot_path: Mapped[str] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(String(64), default="official_fictional_mock")
    status: Mapped[str] = mapped_column(String(32))
    report_json: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class DatasetRow(Base):
    __tablename__ = "service_dataset"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    active_batch_id: Mapped[str] = mapped_column(ForeignKey("service_import_batch.batch_id"))


class ReceptionStateRow(Base):
    __tablename__ = "service_reception_state"

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    seen_revision: Mapped[int] = mapped_column(Integer, default=0)
    source_conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class AssistantCacheRow(Base):
    __tablename__ = "service_assistant_cache"

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ServiceMemoryRow(Base):
    __tablename__ = "service_memory"

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload_json: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class AssistantRunRow(Base):
    __tablename__ = "service_assistant_run"

    run_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    model_id: Mapped[str] = mapped_column(String(128))
    is_mock: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(24))
    trace_json: Mapped[str] = mapped_column(Text)
    usage_json: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ServiceImageObservationRow(Base):
    """Model observations are separate from attachment bytes and immutable business facts."""

    __tablename__ = "service_image_observation"

    attachment_id: Mapped[str] = mapped_column(ForeignKey("attachment.attachment_id"), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    message_id: Mapped[str] = mapped_column(String(128))
    content_sha256: Mapped[str] = mapped_column(String(64))
    analysis_version: Mapped[str] = mapped_column(String(64))
    requested_model: Mapped[str] = mapped_column(String(128))
    model_id: Mapped[str] = mapped_column(String(128))
    is_mock: Mapped[bool] = mapped_column(Boolean)
    payload_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ServiceBreakpointAssessmentRow(Base):
    """Verified semantic findings are not tickets or operator-controlled risk status."""

    __tablename__ = "service_breakpoint_assessment"

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("service_import_batch.batch_id"), index=True)
    assessment_id: Mapped[str] = mapped_column(String(80))
    source_hash: Mapped[str] = mapped_column(String(64))
    analysis_version: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    findings_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class AutoReplyJobRow(Base):
    """Durable generation jobs. Source messages survive model failures."""

    __tablename__ = "service_auto_reply_job"
    __table_args__ = (UniqueConstraint("conversation_id", "message_revision", "mode_revision"),)

    job_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    trigger_message_id: Mapped[str] = mapped_column(String(80))
    message_revision: Mapped[int] = mapped_column(Integer)
    mode_revision: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    reply_message_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ReceptionHandoffRow(Base):
    __tablename__ = "service_reception_handoff"

    conversation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    reason: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ServiceTicketRow(Base):
    """Mutable work tracking, kept separate from imported business facts."""

    __tablename__ = "service_ticket"

    ticket_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_record_id: Mapped[str | None] = mapped_column(String(80), nullable=True, unique=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    buyer_alias: Mapped[str] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    work_order_type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    priority: Mapped[str] = mapped_column(String(16), default="normal")
    assignee: Mapped[str] = mapped_column(String(80), default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ServiceTicketDetailRow(Base):
    """Operator-entered data is not a replacement for the imported work-order detail."""

    __tablename__ = "service_ticket_detail"

    ticket_id: Mapped[str] = mapped_column(ForeignKey("service_ticket.ticket_id"), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)


class ServiceDeskEventRow(Base):
    __tablename__ = "service_desk_event"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(128), index=True)
    entity_kind: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class SourceRecordRow(Base):
    __tablename__ = "service_source_record"
    __table_args__ = (UniqueConstraint("batch_id", "sheet_name", "row_number"),)

    record_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("service_import_batch.batch_id"), index=True)
    sheet_name: Mapped[str] = mapped_column(String(64))
    row_number: Mapped[int] = mapped_column(Integer)
    business_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    values_json: Mapped[str] = mapped_column(Text)
    cell_metadata_json: Mapped[str] = mapped_column(Text)
    row_sha256: Mapped[str] = mapped_column(String(64))


class ServiceConversationRow(Base):
    __tablename__ = "service_conversation"
    __table_args__ = (UniqueConstraint("batch_id", "conversation_id"),)

    record_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("service_import_batch.batch_id"), index=True)
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    buyer_alias: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    aliases_json: Mapped[str] = mapped_column(Text)
    first_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FactMixin:
    record_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("service_import_batch.batch_id"), index=True)
    source_record_id: Mapped[str] = mapped_column(
        ForeignKey("service_source_record.record_id"), unique=True
    )
    conversation_record_id: Mapped[str] = mapped_column(
        ForeignKey("service_conversation.record_id"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    buyer_alias: Mapped[str] = mapped_column(Text, index=True)
    shop: Mapped[str | None] = mapped_column(Text, nullable=True)


class ServiceOrderRow(FactMixin, Base):
    __tablename__ = "service_order"
    __table_args__ = (UniqueConstraint("batch_id", "order_id"),)

    order_id: Mapped[str] = mapped_column(String(128), index=True)
    sku: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paid_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    source_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    ordered_at: Mapped[datetime] = mapped_column(DateTime)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    carrier: Mapped[str | None] = mapped_column(Text, nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    province: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    gift: Mapped[str | None] = mapped_column(Text, nullable=True)
    buyer_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkOrderRow(FactMixin, Base):
    __tablename__ = "service_work_order"
    __table_args__ = (UniqueConstraint("batch_id", "work_order_id"),)

    work_order_id: Mapped[str] = mapped_column(String(128), index=True)
    work_order_type: Mapped[str] = mapped_column(String(32), index=True)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_order.record_id"), nullable=True, index=True
    )
    source_status: Mapped[str] = mapped_column(Text)
    normalized_status: Mapped[str] = mapped_column(String(32))
    handler: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DetailMixin:
    work_order_record_id: Mapped[str] = mapped_column(
        ForeignKey("service_work_order.record_id"), primary_key=True
    )
    fields_json: Mapped[str] = mapped_column(Text)


class ReshipExchangeRow(DetailMixin, Base):
    __tablename__ = "service_reship_exchange"
    service_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_tracking_no: Mapped[str | None] = mapped_column(Text, nullable=True)
    reship_tracking_no: Mapped[str | None] = mapped_column(Text, nullable=True)


class OfflinePaymentRow(DetailMixin, Base):
    __tablename__ = "service_offline_payment"
    refund_amount_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transfer_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LogisticsRow(DetailMixin, Base):
    __tablename__ = "service_logistics"
    issue_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    solution: Mapped[str | None] = mapped_column(Text, nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(Text, nullable=True)


class AdverseReactionRow(DetailMixin, Base):
    __tablename__ = "service_adverse_reaction"
    symptom_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sought_medical_care: Mapped[str | None] = mapped_column(Text, nullable=True)
    stopped_use: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReturnRefundRow(DetailMixin, Base):
    __tablename__ = "service_return_refund"
    return_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    refund_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    abnormal: Mapped[str | None] = mapped_column(Text, nullable=True)


class ServiceMessageRow(FactMixin, Base):
    __tablename__ = "service_message"
    __table_args__ = (
        UniqueConstraint("batch_id", "message_id"),
        UniqueConstraint("batch_id", "conversation_id", "sequence"),
    )

    message_id: Mapped[str] = mapped_column(String(128), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    sent_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    source_role: Mapped[str] = mapped_column(Text)
    sender_role: Mapped[str] = mapped_column(String(32))
    sender: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_major: Mapped[str | None] = mapped_column(Text, nullable=True)
    scene_minor: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_target_buyer_message: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_content_type: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(32))
    chat_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_state: Mapped[str] = mapped_column(String(32), default="not_applicable")
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    work_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_order.record_id"), nullable=True, index=True
    )
    work_order_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_work_order.record_id"), nullable=True, index=True
    )


class ServiceEventRow(Base):
    __tablename__ = "service_event"
    __table_args__ = (UniqueConstraint("source_record_id", "event_type"),)

    event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("service_import_batch.batch_id"), index=True)
    conversation_record_id: Mapped[str] = mapped_column(
        ForeignKey("service_conversation.record_id"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    source_record_id: Mapped[str] = mapped_column(ForeignKey("service_source_record.record_id"))
    entity_record_id: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(32))
    event_type: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class ServiceAiObservationRow(Base):
    __tablename__ = "service_ai_observation"

    observation_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("service_import_batch.batch_id"), index=True)
    conversation_record_id: Mapped[str] = mapped_column(
        ForeignKey("service_conversation.record_id"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    source_message_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_source_record.record_id"), nullable=True, index=True
    )
    emotion_level: Mapped[str] = mapped_column(String(32))
    emotion_trend: Mapped[str] = mapped_column(String(32))
    risk_types_json: Mapped[str] = mapped_column(Text, default="[]")
    risk_level: Mapped[str] = mapped_column(String(32))
    risk_status: Mapped[str] = mapped_column(String(32))
    risk_reason: Mapped[str] = mapped_column(Text, default="")
    current_question: Mapped[str] = mapped_column(Text, default="")
    service_summary: Mapped[str] = mapped_column(Text, default="")
    missing_information_json: Mapped[str] = mapped_column(Text, default="[]")
    next_steps_json: Mapped[str] = mapped_column(Text, default="[]")
    reply_suggestions_json: Mapped[str] = mapped_column(Text, default="[]")
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    model_id: Mapped[str] = mapped_column(String(128))
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ServiceRiskAlertRow(Base):
    __tablename__ = "service_risk_alert"
    # 客户页新建的会话不在导入批次里，没有 conversation_record_id；唯一性按会话 ID 判断。
    __table_args__ = (UniqueConstraint("batch_id", "conversation_id", "risk_type"),)

    alert_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("service_import_batch.batch_id"), index=True)
    conversation_record_id: Mapped[str | None] = mapped_column(
        ForeignKey("service_conversation.record_id"), nullable=True, index=True
    )
    conversation_id: Mapped[str] = mapped_column(String(128), index=True)
    buyer_alias: Mapped[str] = mapped_column(Text, index=True)
    order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    work_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    risk_type: Mapped[str] = mapped_column(String(64), index=True)
    risk_level: Mapped[str] = mapped_column(String(32), index=True)
    risk_status: Mapped[str] = mapped_column(String(32), index=True)
    trigger_summary: Mapped[str] = mapped_column(Text, default="")
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    recommended_action: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    handled_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    handled_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class RiskLifecycleRow(Base):
    """Rule observations are separate from operator-controlled risk status."""

    __tablename__ = "service_risk_lifecycle"

    alert_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    episode: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    rule_version: Mapped[str] = mapped_column(String(64), default="legacy")
    signal_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    order_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    work_order_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    conditions_json: Mapped[str] = mapped_column(Text, default="{}")
    incident_ids_json: Mapped[str] = mapped_column(Text, default="[]")


class RiskEpisodeRow(Base):
    __tablename__ = "service_risk_episode"
    __table_args__ = (UniqueConstraint("alert_id", "episode"),)

    episode_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    alert_id: Mapped[str] = mapped_column(String(80), index=True)
    episode: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[str] = mapped_column(Text)
    closed_at: Mapped[datetime] = mapped_column(DateTime)


class RiskJudgmentRow(Base):
    """Append-only operator judgments are separate from handling or source facts."""

    __tablename__ = "service_risk_judgment"

    judgment_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("service_import_batch.batch_id"), index=True)
    alert_id: Mapped[str] = mapped_column(String(80), index=True)
    episode: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(Text)
    detection_hash: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[str] = mapped_column(Text)
    supersedes_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


def migrate_risk_alert_table(engine: Engine) -> None:
    """旧版预警表的会话记录 ID 非空且唯一约束不同，SQLite 只能重建表。

    已有预警（含处理记录）原样复制到新表，不丢状态。
    """

    with engine.begin() as connection:
        row = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='service_risk_alert'"
        ).first()
        if row is None or "conversation_record_id VARCHAR(80) NOT NULL" not in row[0]:
            return
        connection.exec_driver_sql("ALTER TABLE service_risk_alert RENAME TO _risk_alert_old")
        # 旧表的索引名仍被占用，先删掉，新表建好后再复制数据。
        for (name,) in connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='_risk_alert_old' "
            "AND sql IS NOT NULL"
        ).all():
            connection.exec_driver_sql(f'DROP INDEX "{name}"')
        ServiceRiskAlertRow.__table__.create(connection)
        columns = ", ".join(column.name for column in ServiceRiskAlertRow.__table__.columns)
        connection.exec_driver_sql(
            f"INSERT INTO service_risk_alert ({columns}) SELECT {columns} FROM _risk_alert_old"
        )
        connection.exec_driver_sql("DROP TABLE _risk_alert_old")


DETAIL_MODELS = {
    "reship_exchange": ReshipExchangeRow,
    "offline_payment": OfflinePaymentRow,
    "logistics": LogisticsRow,
    "adverse_reaction": AdverseReactionRow,
    "return_refund": ReturnRefundRow,
}

# SQLite guards also reject bulk SQL updates/deletes, not just ORM attribute changes.
IMMUTABLE_MODELS = (
    SourceRecordRow,
    ServiceConversationRow,
    ServiceOrderRow,
    WorkOrderRow,
    ServiceMessageRow,
    ServiceEventRow,
    RiskEpisodeRow,
    RiskJudgmentRow,
    *DETAIL_MODELS.values(),
)
for _model in IMMUTABLE_MODELS:
    for _operation in ("UPDATE", "DELETE"):
        _table = _model.__tablename__
        event.listen(
            _model.__table__,
            "after_create",
            DDL(
                f"CREATE TRIGGER IF NOT EXISTS immutable_{_table}_{_operation.lower()} "
                f"BEFORE {_operation} ON {_table} "
                "BEGIN SELECT RAISE(ABORT, 'imported source facts are immutable'); END"
            ).execute_if(dialect="sqlite"),
        )
