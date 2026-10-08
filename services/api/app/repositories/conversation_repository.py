"""会话、消息与案件的仓储层。

关键不变量：
- 会话只有一个案件（`conversation_id` 唯一）；
- 幂等消息：同一 `(conversation_id, client_message_key)` 重复提交返回**已有**消息，
  不追加第二条，也不递增 `message_revision`；
- `message_revision` 只在**新消息真正落库**时递增，因此候选过期判断可靠。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, attributes

from app.config import get_settings
from app.domain.case_state.models import (
    AfterSalesRequestRow,
    AttachmentRow,
    CaseEventRow,
    CaseRow,
    ConversationRow,
    MessageRow,
    new_id,
)
from app.domain.enums import (
    CaseStatus,
    ComplaintRisk,
    ConversationStage,
    EmotionLevel,
    RatingStatus,
    SenderRole,
    ServiceMode,
    TroubleshootingResult,
)


def _now() -> datetime:
    return datetime.now(UTC)


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        # 删除附件文件时需要运行目录（相对路径按运行目录解析）
        self._settings = get_settings()

    # ------------------------------------------------------------------ 会话

    def create_conversation(
        self, *, customer_id: str, title: str = "新会话", conversation_id: str | None = None
    ) -> ConversationRow:
        row = ConversationRow(
            conversation_id=conversation_id or new_id("conv"),
            customer_id=customer_id,
            title=title[:200],
            service_mode=ServiceMode.AUTONOMOUS.value,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def get_conversation(self, conversation_id: str) -> ConversationRow | None:
        return self._session.get(ConversationRow, conversation_id)

    def list_conversations(self, *, customer_id: str | None = None) -> list[ConversationRow]:
        statement = select(ConversationRow).order_by(ConversationRow.updated_at.desc())
        if customer_id:
            statement = statement.where(ConversationRow.customer_id == customer_id)
        return list(self._session.execute(statement).scalars())

    def touch_conversation(self, conversation: ConversationRow) -> None:
        conversation.updated_at = _now()
        self._session.flush()

    # ------------------------------------------------------------------ 消息

    def append_message(
        self,
        conversation: ConversationRow,
        *,
        sender_role: SenderRole,
        body: str,
        client_message_key: str,
        attachments: list[dict[str, object]] | None = None,
    ) -> tuple[MessageRow, bool]:
        """追加消息。返回 (消息, 是否新建)。

        幂等：同一 `client_message_key` 已存在时返回已有消息且 `created=False`，
        调用方据此避免重复发送与重复事件。首条客户消息同时用于生成会话标题。
        """

        existing = self._session.execute(
            select(MessageRow).where(
                MessageRow.conversation_id == conversation.conversation_id,
                MessageRow.client_message_key == client_message_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

        # Reserve the next revision in SQLite, including when takeover races an AI delivery.
        revision = self._session.execute(
            update(ConversationRow).where(
                ConversationRow.conversation_id == conversation.conversation_id,
            ).values(message_revision=ConversationRow.message_revision + 1, updated_at=_now())
            .returning(ConversationRow.message_revision)
            .execution_options(synchronize_session=False)
        ).scalar_one()
        attributes.set_committed_value(conversation, "message_revision", revision)
        row = MessageRow(
            message_id=new_id("msg"),
            conversation_id=conversation.conversation_id,
            sender_role=sender_role.value,
            body=body,
            applies_to_message_revision=conversation.message_revision,
            client_message_key=client_message_key,
            attachments_json=json.dumps(attachments or [], ensure_ascii=False),
        )
        self._session.add(row)
        conversation.updated_at = _now()

        # 首条客户消息可作为标题（前端规范：暂取前 16 个字符）
        if sender_role is SenderRole.CUSTOMER and conversation.title == "新会话" and body.strip():
            conversation.title = body.strip()[:16]

        # 注意：这里不能对 flush 做「撞锁重试」。flush 失败后 SQLAlchemy 会把
        # 会话标记为必须回滚，继续使用会抛 PendingRollbackError（已实测）。
        # 锁竞争由连接级 busy_timeout 兜底（见 app/db.py）。
        try:
            self._session.flush()
        except IntegrityError:
            # 幂等竞争：同一 client_message_key 的两个请求可能都在对方提交前
            # 完成「是否已存在」的读取，于是都走到 INSERT，后到者撞上唯一约束
            # （并发重放同一幂等键时稳定复现 500）。
            #
            # 这是**预期内的并发形态**，不应变成 500。此处回滚后重读：该 INSERT
            # 是本事务的第一次写入（此前只有 SELECT），回滚不会丢掉其它内容；
            # 重读能拿到先到者已提交的那一行。
            self._session.rollback()
            existing_row = self._session.execute(
                select(MessageRow).where(
                    MessageRow.conversation_id == conversation.conversation_id,
                    MessageRow.client_message_key == client_message_key,
                )
            ).scalar_one_or_none()
            if existing_row is None:
                # 不是幂等竞争，而是别的完整性问题：原样抛出，不能吞掉
                raise
            return existing_row, False
        return row, True

    def list_messages(self, conversation_id: str) -> list[MessageRow]:
        statement = (
            select(MessageRow)
            .where(MessageRow.conversation_id == conversation_id)
            .order_by(MessageRow.applies_to_message_revision.asc(), MessageRow.created_at.asc())
        )
        return list(self._session.execute(statement).scalars())

    def count_messages(self, conversation_id: str) -> int:
        return int(
            self._session.execute(
                select(func.count(MessageRow.message_id)).where(
                    MessageRow.conversation_id == conversation_id
                )
            ).scalar_one()
        )

    def add_attachment(
        self,
        *,
        conversation_id: str,
        message_id: str | None,
        mime_type: str,
        byte_size: int,
        stored_path: str,
        sha256: str,
        width: int | None = None,
        height: int | None = None,
    ) -> AttachmentRow:
        row = AttachmentRow(
            attachment_id=new_id("att"),
            conversation_id=conversation_id,
            message_id=message_id,
            mime_type=mime_type,
            byte_size=byte_size,
            stored_path=stored_path,
            sha256=sha256,
            width=width,
            height=height,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def list_attachments(self, attachment_ids: list[str]) -> list[AttachmentRow]:
        """按 ID 批量取附件，保持传入顺序，找不到的直接忽略。"""

        if not attachment_ids:
            return []
        rows = list(
            self._session.execute(
                select(AttachmentRow).where(AttachmentRow.attachment_id.in_(attachment_ids))
            ).scalars()
        )
        by_id = {row.attachment_id: row for row in rows}
        return [by_id[item] for item in attachment_ids if item in by_id]

    def link_attachments(self, attachment_ids: list[str], message_id: str) -> None:
        """把附件挂到消息上。

        为什么需要显式关联：上传时还不知道会落到哪条消息（前端是先传图再发送）。
        不建立这个关联，图片就永远只是「孤儿附件」——既不属于任何消息，
        也不会被视觉模型看到（实测过：客户传了图，消息里却什么都没有）。
        """

        for row in self.list_attachments(attachment_ids):
            row.message_id = message_id
        self._session.flush()

    # ------------------------------------------------------------------ 服务模式

    def delete_conversation(self, conversation_id: str) -> dict[str, int]:
        """删除一个会话及其全部依赖数据，返回删除行数（会话本身不存在则报 404）。

        顺序：先按 case 删案件相关（事件、申请），再删消息/附件/候选，最后删会话。
        附件文件在删行之前读出来一并删除，避免留下孤儿文件。
        """

        from app.domain.case_state.models import (
            AfterSalesRequestRow,
            AiSuggestionRow,
            AttachmentRow,
            CaseEventRow,
            CaseRow,
            MessageRow,
        )

        conversation = self.get_conversation(conversation_id)
        if conversation is None:
            from app.errors import NotFoundError

            raise NotFoundError(f"会话不存在：{conversation_id}")

        case_ids = [
            row.case_id
            for row in self._session.execute(
                select(CaseRow).where(CaseRow.conversation_id == conversation_id)
            )
            .scalars()
            .all()
        ]

        counts: dict[str, int] = {}
        if case_ids:
            counts["requests"] = (
                self._session.query(AfterSalesRequestRow)
                .filter(AfterSalesRequestRow.case_id.in_(case_ids))
                .delete(synchronize_session=False)
            )
            counts["case_events"] = (
                self._session.query(CaseEventRow)
                .filter(CaseEventRow.case_id.in_(case_ids))
                .delete(synchronize_session=False)
            )
            counts["cases"] = (
                self._session.query(CaseRow)
                .filter(CaseRow.case_id.in_(case_ids))
                .delete(synchronize_session=False)
            )

        # 附件：先取路径，再删行，最后删文件
        attachments = (
            self._session.execute(
                select(AttachmentRow).where(AttachmentRow.conversation_id == conversation_id)
            )
            .scalars()
            .all()
        )
        stored_paths = [row.stored_path for row in attachments]
        counts["attachments"] = (
            self._session.query(AttachmentRow)
            .filter(AttachmentRow.conversation_id == conversation_id)
            .delete(synchronize_session=False)
        )
        counts["suggestions"] = (
            self._session.query(AiSuggestionRow)
            .filter(AiSuggestionRow.conversation_id == conversation_id)
            .delete(synchronize_session=False)
        )
        counts["messages"] = (
            self._session.query(MessageRow)
            .filter(MessageRow.conversation_id == conversation_id)
            .delete(synchronize_session=False)
        )
        self._session.delete(conversation)
        self._session.flush()

        counts["conversations"] = 1
        counts["attachment_files"] = self._delete_attachment_files(stored_paths)
        return counts

    def _delete_attachment_files(self, stored_paths: list[str]) -> int:
        """删除附件文件。路径只来自系统生成值，缺失或不可删都不影响主流程。"""

        removed = 0
        for raw in stored_paths:
            try:
                path = Path(raw)
                if not path.is_absolute():
                    path = self._settings.runtime_path / path
                if path.is_file():
                    path.unlink()
                    removed += 1
            except OSError:
                # 文件删不掉不该让整个删除失败：库里的记录已经删了，
                # 残留文件由运行目录清理流程处理（手册第 6 节）。
                continue
        return removed

    def set_service_mode(self, conversation: ConversationRow, mode: ServiceMode) -> bool:
        """接管/恢复托管是独立操作。返回是否真的发生变化。"""

        if conversation.service_mode == mode.value:
            return False
        conversation.service_mode = mode.value
        conversation.mode_revision += 1
        conversation.updated_at = _now()
        self._session.flush()
        return True

    # ------------------------------------------------------------------ 案件

    def get_case_by_conversation(self, conversation_id: str) -> CaseRow | None:
        return self._session.execute(
            select(CaseRow).where(CaseRow.conversation_id == conversation_id)
        ).scalar_one_or_none()

    def get_case(self, case_id: str) -> CaseRow | None:
        return self._session.get(CaseRow, case_id)

    def create_case_for_conversation(self, conversation: ConversationRow) -> tuple[CaseRow, bool]:
        """首条有效客户消息到达时创建案件；空会话不算已经开始售后。

        重复调用返回已有案件且 `created=False`（幂等）。
        """

        existing = self.get_case_by_conversation(conversation.conversation_id)
        if existing is not None:
            return existing, False

        row = CaseRow(
            case_id=new_id("case"),
            conversation_id=conversation.conversation_id,
            customer_id=conversation.customer_id,
            case_status=CaseStatus.OPEN.value,
            conversation_stage=ConversationStage.INTAKE.value,
        )
        self._session.add(row)
        self._session.flush()
        self.record_event(
            row,
            event_type="case_created",
            actor_type="system",
            to_state=CaseStatus.OPEN.value,
            detail={"conversation_id": conversation.conversation_id},
        )
        return row, True

    def record_event(
        self,
        case: CaseRow,
        *,
        event_type: str,
        actor_type: str,
        from_state: str | None = None,
        to_state: str | None = None,
        detail: dict[str, object] | None = None,
    ) -> CaseEventRow:
        row = CaseEventRow(
            event_id=new_id("evt"),
            case_id=case.case_id,
            conversation_id=case.conversation_id,
            event_type=event_type,
            from_state=from_state,
            to_state=to_state,
            actor_type=actor_type,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def set_case_status(
        self, case: CaseRow, target: CaseStatus, *, actor_type: str = "system"
    ) -> bool:
        """状态转换必须经状态机校验；同一状态按幂等处理。"""

        from app.domain.case_state.state_machine import assert_case_transition

        current = CaseStatus(case.case_status)
        assert_case_transition(current, target)
        if current is target:
            return False
        case.case_status = target.value
        case.updated_at = _now()
        if target is CaseStatus.CLOSED:
            case.closed_at = _now()
        self._session.flush()
        self.record_event(
            case,
            event_type="case_status_changed",
            actor_type=actor_type,
            from_state=current.value,
            to_state=target.value,
        )
        return True

    def set_stage(self, case: CaseRow, target: ConversationStage) -> bool:
        from app.domain.case_state.state_machine import can_transition_stage

        current = ConversationStage(case.conversation_stage)
        result = can_transition_stage(current, target)
        if not result.allowed:
            from app.errors import ValidationRejected

            raise ValidationRejected(result.reason)
        if current is target:
            return False
        case.conversation_stage = target.value
        case.updated_at = _now()
        self._session.flush()
        return True

    def update_case_facts(
        self,
        case: CaseRow,
        *,
        product_id: str | None = None,
        product_model: str | None = None,
        product_category: str | None = None,
        country_code: str | None = None,
        purchase_channel: str | None = None,
        seller_name_raw: str | None = None,
        seller_name_standard: str | None = None,
        intents: list[str] | None = None,
        facts: dict[str, object] | None = None,
        missing_facts: list[str] | None = None,
        emotion_level: EmotionLevel | None = None,
        complaint_risk: ComplaintRisk | None = None,
        warranty_status: str | None = None,
        dealer_authorization_status: str | None = None,
        knowledge_hit_status: str | None = None,
        retrieval_id: str | None = None,
        troubleshooting_result: TroubleshootingResult | None = None,
        closure_reason: str | None = None,
    ) -> None:
        """更新案件事实。

        注意：`seller_name_standard` 只在传入非空值时才写入，
        调用方不得用用户输入或相似度结果覆盖它（AC-19）。
        """

        if product_id is not None:
            case.product_id = product_id
        if product_model is not None:
            case.product_model = product_model
        if product_category is not None:
            case.product_category = product_category
        if country_code is not None:
            case.country_code = country_code
        if purchase_channel is not None:
            case.purchase_channel = purchase_channel
        if seller_name_raw is not None:
            case.seller_name_raw = seller_name_raw
        if seller_name_standard is not None:
            case.seller_name_standard = seller_name_standard
        if intents is not None:
            case.customer_intents_json = json.dumps(intents, ensure_ascii=False)
        if facts is not None:
            case.case_facts_json = json.dumps(facts, ensure_ascii=False)
        if missing_facts is not None:
            case.missing_facts_json = json.dumps(missing_facts, ensure_ascii=False)
        if emotion_level is not None:
            case.emotion_level = emotion_level.value
        if complaint_risk is not None:
            case.complaint_risk = complaint_risk.value
        if warranty_status is not None:
            case.warranty_status = warranty_status
        if dealer_authorization_status is not None:
            case.dealer_authorization_status = dealer_authorization_status
        if knowledge_hit_status is not None:
            case.knowledge_hit_status = knowledge_hit_status
        if retrieval_id is not None:
            case.retrieval_id = retrieval_id
        if troubleshooting_result is not None:
            case.troubleshooting_result = troubleshooting_result.value
        if closure_reason is not None:
            case.closure_reason = closure_reason
        case.updated_at = _now()
        self._session.flush()

    def set_rating(self, case: CaseRow, *, status: RatingStatus, rating: int | None = None) -> None:
        """写入评价。评分可以是空值（跳过），但绝不能填默认分。"""

        if rating is not None and not 1 <= rating <= 5:
            from app.errors import ValidationRejected

            raise ValidationRejected(f"评分必须是 1—5 的整数，收到 {rating}")
        case.rating_status = status.value
        case.user_rating = rating
        case.updated_at = _now()
        self._session.flush()

    def list_open_requests(self, case_id: str) -> list[AfterSalesRequestRow]:
        from app.domain.enums import RequestStatus

        statement = select(AfterSalesRequestRow).where(
            AfterSalesRequestRow.case_id == case_id,
            AfterSalesRequestRow.request_status.in_(
                [
                    RequestStatus.DRAFT.value,
                    RequestStatus.PENDING_CONFIRMATION.value,
                    RequestStatus.NEEDS_INFORMATION.value,
                ]
            ),
        )
        return list(self._session.execute(statement).scalars())
