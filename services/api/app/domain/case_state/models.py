"""会话、消息与案件的持久化模型。

事实来源（工程规范第 13.1 节）：后端数据库是已发送消息、案件、申请、评价和
知识清单的**唯一事实来源**；浏览器只保存界面偏好与未发送草稿。

并发要求（第 13.2 节）：
- 每会话有 `message_revision`、`service_mode`、`mode_revision`；
- 消息通过**幂等请求**落库再生成事件，失败重试不追加重复消息；
- 视角切换不改服务模式。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ConversationRow(Base):
    """会话。客户新建独立会话，客服侧可看到同一会话。"""

    __tablename__ = "conversation"

    conversation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    customer_id: Mapped[str] = mapped_column(String(64), index=True)
    # 服务模式与页面视角无关：打开客服工作台不自动暂停 AI
    service_mode: Mapped[str] = mapped_column(String(32), default="autonomous")
    message_revision: Mapped[int] = mapped_column(Integer, default=0)
    mode_revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    messages: Mapped[list[MessageRow]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class MessageRow(Base):
    """消息。发送方持久化记录，渲染方向由当前视角计算，数据本身不翻转。"""

    __tablename__ = "message"
    __table_args__ = (
        # 幂等键唯一：同一会话内重复提交同一键不会追加第二条消息
        UniqueConstraint("conversation_id", "client_message_key", name="uq_message_idempotency"),
    )

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversation.conversation_id"), index=True
    )
    sender_role: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text, default="")
    # 草稿阶段即生成，用于「采用不等于发送」与候选过期判断
    applies_to_message_revision: Mapped[int] = mapped_column(Integer, default=0)
    client_message_key: Mapped[str] = mapped_column(String(80), default="")
    attachments_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    conversation: Mapped[ConversationRow] = relationship(back_populates="messages")


class AttachmentRow(Base):
    """附件。只保存到 data/runtime 下的系统生成路径，不保存原始文件名。"""

    __tablename__ = "attachment"

    attachment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    message_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    mime_type: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    stored_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CaseRow(Base):
    """案件。首条有效客户消息到达时创建，空会话不算已经开始了售后。"""

    __tablename__ = "case"

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversation.conversation_id"), index=True, unique=True
    )
    customer_id: Mapped[str] = mapped_column(String(64), index=True)

    case_status: Mapped[str] = mapped_column(String(32), default="open")
    conversation_stage: Mapped[str] = mapped_column(String(32), default="intake")

    product_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    product_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    purchase_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 卖家原始名与标准名分开保存；未唯一匹配时标准名为空，不得虚构
    seller_name_raw: Mapped[str | None] = mapped_column(String(200), nullable=True)
    seller_name_standard: Mapped[str | None] = mapped_column(String(200), nullable=True)

    customer_intents_json: Mapped[str] = mapped_column(Text, default="[]")
    case_facts_json: Mapped[str] = mapped_column(Text, default="{}")
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")

    knowledge_hit_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retrieval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    emotion_level: Mapped[str] = mapped_column(String(32), default="unknown")
    complaint_risk: Mapped[str] = mapped_column(String(32), default="unknown")

    warranty_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dealer_authorization_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    troubleshooting_result: Mapped[str] = mapped_column(String(32), default="not_attempted")

    rating_status: Mapped[str] = mapped_column(String(32), default="not_requested")
    user_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)

    missing_facts_json: Mapped[str] = mapped_column(Text, default="[]")
    closure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 同一必要事实连续澄清的轮次，用于「两轮无新增信息则停止重复追问」
    clarification_attempts: Mapped[int] = mapped_column(Integer, default=0)

    service_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CaseEventRow(Base):
    """案件状态事件。任何状态变更都记录事件（工程规范第 4.2 节）。"""

    __tablename__ = "case_event"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("case.case_id"), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32), default="system")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AfterSalesRequestRow(Base):
    """售后申请。本期只生成草稿并等待 Demo 客服确认，不执行真实业务动作。"""

    __tablename__ = "after_sales_request"

    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("case.case_id"), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    request_type: Mapped[str] = mapped_column(String(32))
    request_status: Mapped[str] = mapped_column(String(32), default="draft")

    # 批准绑定「申请内容版本」：内容或依据变化必须使旧确认失效
    request_revision: Mapped[int] = mapped_column(Integer, default=1)
    payload_hash: Mapped[str] = mapped_column(String(64), default="")
    request_payload_json: Mapped[str] = mapped_column(Text, default="{}")

    # 幂等：同一 (case_id, request_type, payload_hash, request_revision) 只允许一条
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)

    reviewer_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 已生效的批准所对应的版本；重复批准同一版本不重复记账
    approved_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class AiSuggestionRow(Base):
    """客服话术候选。绑定 (conversation_id, message_revision)，新消息使其过期。"""

    __tablename__ = "ai_suggestion"

    suggestion_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    message_revision: Mapped[int] = mapped_column(Integer)
    variant: Mapped[str] = mapped_column(String(32))
    body: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(64), default="agent")
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    # 采用/忽略是独立动作，与发送分离
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditEventRow(Base):
    """追加式审计。不被业务状态覆盖，且默认不保存完整 prompt/output。"""

    __tablename__ = "audit_event"

    audit_event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    case_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(32))

    event_type: Mapped[str] = mapped_column(String(64))
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    knowledge_snapshot_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_schema_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    human_confirmation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── 平台表注册（务必留在文件末尾）─────────────────────────────────────────
# 平台表（运行设置 / 提示词模板）复用本模块的 `Base`，但它们是**另一个模块**里声明的。
# 只有导入过那个模块，`create_all(Base.metadata)` 才会建出这两张表；
# 测试夹具与隔离播种脚本都只导入本模块，曾经因此出现
# `no such table: prompt_template`（与缺陷第 39 项同源）。
# 放在文件末尾导入：此时 `Base` 与全部实体已定义，不会形成循环依赖。
from app.domain.platform import models as _platform_models  # noqa: E402,F401
