"""Unified reception over immutable imported history and mutable local messages."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditContext, AuditRecorder
from app.domain.case_state.models import CaseRow, ConversationRow, MessageRow
from app.domain.consumer_service.emotion import score_message
from app.domain.consumer_service.mapping import DATASET_ID
from app.domain.consumer_service.models import (
    DatasetRow,
    ReceptionStateRow,
    ServiceMessageRow,
    ServiceRiskAlertRow,
    ServiceTicketRow,
    WorkOrderRow,
)
from app.domain.consumer_service.risk import current_signal_attention, risk_alert_view
from app.domain.enums import SenderRole, ServiceMode, ServiceRiskType
from app.errors import ConflictError, NotFoundError, ValidationRejected
from app.repositories.consumer_service import ConsumerServiceRepository, _work_order_view
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.conversation_service import message_view
from app.schemas.consumer_service import ReceptionItemView, ReceptionSnapshotView
from app.schemas.conversation import MessageView


def active_batch(session: Session) -> str | None:
    row = session.get(DatasetRow, DATASET_ID)
    return row.active_batch_id if row else None


def risk_service_states(session: Session) -> dict[str, tuple[str, str | None]]:
    from app.domain.consumer_service.risk_rules import utc

    imported = {
        item.conversation_id for item in ConsumerServiceRepository(session).queue()
    }
    local = set(session.scalars(select(ConversationRow.conversation_id)))
    messages = list(session.scalars(select(MessageRow).where(
        MessageRow.sender_role.in_(["customer", "operator"]),
    )))
    working = (local - imported) | {message.conversation_id for message in messages}
    # A new follow-up can exist on an imported conversation without a local chat shell.
    working.update(session.scalars(select(ServiceTicketRow.conversation_id)))
    working.update(session.scalars(select(ServiceRiskAlertRow.conversation_id).where(
        ServiceRiskAlertRow.batch_id == active_batch(session),
        ServiceRiskAlertRow.risk_status == "in_progress",
        ServiceRiskAlertRow.handled_at.is_not(None),
    )))
    cases = {row.conversation_id: row for row in session.scalars(select(CaseRow))}
    latest_customer: dict[str, datetime] = {}
    for message in messages:
        if message.sender_role == "customer":
            at = utc(message.created_at)
            previous = latest_customer.get(message.conversation_id)
            if previous is None or at > previous:
                latest_customer[message.conversation_id] = at
    states = dict.fromkeys(imported | local, ("historical", None))
    for cid in working:
        case = cases.get(cid)
        closed = utc(case.closed_at) if case and case.case_status == "closed" else None
        latest = latest_customer.get(cid)
        if closed is not None and (latest is None or latest <= closed):
            states[cid] = ("closed", closed.replace(tzinfo=UTC).isoformat())
        else:
            states[cid] = ("live", None)
    return states


def reception_snapshot(session: Session) -> ReceptionSnapshotView:
    from app.domain.consumer_service.auto_reception import HANDOFF_REASONS, latest_jobs
    from app.domain.consumer_service.models import ReceptionHandoffRow
    from app.domain.consumer_service.risk_judgments import latest_judgments

    jobs = latest_jobs(session)
    handoffs = {r.conversation_id: r for r in session.scalars(select(ReceptionHandoffRow))}
    batch = active_batch(session)
    sources = ConsumerServiceRepository(session).queue()
    runtime = list(session.scalars(select(ConversationRow)))
    messages = list(session.scalars(select(MessageRow).order_by(MessageRow.created_at)))
    by_conversation: dict[str, list[MessageRow]] = defaultdict(list)
    for message in messages:
        by_conversation[message.conversation_id].append(message)
    states = {row.conversation_id: row for row in session.scalars(select(ReceptionStateRow))}
    source_messages = (
        list(
            session.scalars(
                select(ServiceMessageRow)
                .where(ServiceMessageRow.batch_id == batch)
                .order_by(ServiceMessageRow.sent_at, ServiceMessageRow.sequence)
            )
        )
        if batch
        else []
    )
    last_source = {row.conversation_id: row for row in source_messages}
    last_customer_source: dict[str, ServiceMessageRow] = {}
    for row in source_messages:
        if row.sender_role == "customer":
            last_customer_source[row.conversation_id] = row
    emotion_labels = {0: "calm", 1: "dissatisfied", 2: "angry"}

    def current_emotion(local_messages: list[MessageRow], source_message):
        candidates = [
            message for message in local_messages
            if message.sender_role == "customer" and message.body
        ]
        if candidates:
            return emotion_labels.get(score_message(candidates[-1].body))
        if source_message and source_message.body:
            return emotion_labels.get(score_message(source_message.body))
        return None

    risks: dict[str, str] = {}
    active_risks: dict[str, list[ServiceRiskType]] = defaultdict(list)
    review_risks: dict[str, list[ServiceRiskType]] = defaultdict(list)

    if batch:
        local_message_ids = {message.message_id for message in messages}
        local_ticket_ids = set(session.scalars(select(ServiceTicketRow.ticket_id)))
        risk_rows = list(session.scalars(select(ServiceRiskAlertRow).where(
            ServiceRiskAlertRow.batch_id == batch,
            ServiceRiskAlertRow.risk_status.in_(["pending", "in_progress"]),
        )))
        judgments = latest_judgments(session, [row.alert_id for row in risk_rows])
        for row in risk_rows:
            attention = current_signal_attention(
                risk_alert_view(row, session), local_message_ids=local_message_ids,
                local_ticket_ids=local_ticket_ids,
                judgment=judgments.get(row.alert_id),
            )
            if attention in {"historical", "closed"}:
                continue
            if attention == "active":
                if row.risk_level == "high":
                    risks[row.conversation_id] = "high"
                active_risks[row.conversation_id].append(ServiceRiskType(row.risk_type))
            else:
                review_risks[row.conversation_id].append(ServiceRiskType(row.risk_type))
        for conversation_id in active_risks:
            active_risks[conversation_id] = list(dict.fromkeys(active_risks[conversation_id]))
        for conversation_id in review_risks:
            review_risks[conversation_id] = list(dict.fromkeys(review_risks[conversation_id]))

    items: dict[str, ReceptionItemView] = {}
    for source in sources:
        last = last_source.get(source.conversation_id)
        items[source.conversation_id] = ReceptionItemView(
            conversation_id=source.conversation_id,
            buyer_alias=source.customer_id,
            title=source.title,
            preview=last.body or "" if last else "",
            updated_at=source.updated_at,
            data_source="imported",
            message_revision=0,
            unread_count=0,
            risk_level=risks.get(source.conversation_id),
            current_emotion=current_emotion(
                [], last_customer_source.get(source.conversation_id),
            ),
            active_risk_types=active_risks.get(source.conversation_id, []),
            review_risk_types=review_risks.get(source.conversation_id, []),
        )
    for row in runtime:
        history = by_conversation.get(row.conversation_id, [])
        state = states.get(row.conversation_id)
        seen = state.seen_revision if state else 0
        unread = sum(
            m.sender_role == "customer" and m.applies_to_message_revision > seen for m in history
        )
        last = history[-1] if history else None
        source = items.get(row.conversation_id)
        items[row.conversation_id] = ReceptionItemView(
            conversation_id=row.conversation_id,
            buyer_alias=source.buyer_alias if source else row.customer_id,
            title=source.title if source else row.title,
            preview=last.body if last else source.preview if source else "",
            updated_at=(
                row.updated_at.replace(tzinfo=UTC)
                if row.updated_at.tzinfo is None
                else row.updated_at
            ).isoformat(),
            data_source="live",
            message_revision=row.message_revision,
            unread_count=unread,
            risk_level=risks.get(row.conversation_id),
            current_emotion=current_emotion(
                history, last_customer_source.get(row.conversation_id),
            ),
            active_risk_types=active_risks.get(row.conversation_id, []),
            review_risk_types=review_risks.get(row.conversation_id, []),
            service_mode=ServiceMode(row.service_mode),
            mode_revision=row.mode_revision,
            auto_reply_status=jobs[row.conversation_id].status if row.conversation_id in jobs else "idle",
            handoff_reason=HANDOFF_REASONS.get(handoffs[row.conversation_id].reason, "待人工跟进")
            if row.conversation_id in handoffs else None,
        )
    ordered = sorted(
        items.values(),
        key=lambda item: (item.data_source == "live", item.unread_count > 0, item.updated_at),
        reverse=True,
    )
    return ReceptionSnapshotView(
        items=ordered, unread_total=sum(item.unread_count for item in ordered)
    )


def conversation_messages(session: Session, conversation_id: str) -> list[MessageView]:
    batch = active_batch(session)
    imported = (
        list(
            session.scalars(
                select(ServiceMessageRow)
                .where(
                    ServiceMessageRow.batch_id == batch,
                    ServiceMessageRow.conversation_id == conversation_id,
                )
                .order_by(ServiceMessageRow.sent_at, ServiceMessageRow.sequence)
            )
        )
        if batch
        else []
    )
    local = session.get(ConversationRow, conversation_id)
    if not imported and local is None:
        raise NotFoundError("会话不存在")
    source_views = [
        MessageView(
            message_id=row.message_id,
            conversation_id=conversation_id,
            sender_role=SenderRole(row.sender_role),
            body=row.body or "",
            message_revision=row.sequence,
            created_at=row.sent_at.isoformat(),
            attachments=[],
        )
        for row in imported
    ]
    return source_views + [
        message_view(row) for row in ConversationRepository(session).list_messages(conversation_id)
    ]


def ensure_local_conversation(session: Session, conversation_id: str) -> ConversationRow:
    repo = ConversationRepository(session)
    row = repo.get_conversation(conversation_id)
    if row is None:
        context = ConsumerServiceRepository(session).context(conversation_id)
        row = repo.create_conversation(
            conversation_id=conversation_id,
            customer_id=context.buyer_alias,
            title=context.buyer_alias,
        )
        row.service_mode = ServiceMode.OPERATOR_ASSISTED.value
        session.flush()
    return row


def mark_seen(session: Session, conversation_id: str, revision: int) -> None:
    conversation = session.get(ConversationRow, conversation_id)
    if conversation is None:
        return
    state = session.get(ReceptionStateRow, conversation_id)
    if state is None:
        state = ReceptionStateRow(conversation_id=conversation_id, seen_revision=0)
        session.add(state)
    state.seen_revision = max(state.seen_revision, min(revision, conversation.message_revision))
    session.flush()


def send_operator(
    session: Session, conversation_id: str, body: str, key: str,
    attachment_ids: list[str] | None = None,
) -> MessageView:
    conversation = ensure_local_conversation(session, conversation_id)
    if conversation.service_mode == ServiceMode.AUTONOMOUS.value:
        raise ConflictError("请先接管会话，再发送人工回复")
    repo = ConversationRepository(session)
    attachments = repo.list_attachments(attachment_ids or [])
    if len(attachments) != len(set(attachment_ids or [])):
        raise ValidationRejected("存在无效的附件编号")
    if any(item.conversation_id != conversation_id for item in attachments):
        raise ValidationRejected("附件归属与当前会话不符")
    if not body.strip() and not attachments:
        raise ValidationRejected("请填写消息或添加图片")
    row, created = repo.append_message(
        conversation,
        sender_role=SenderRole.OPERATOR,
        body=body,
        client_message_key=key,
        attachments=[
            {
                "attachmentId": item.attachment_id, "mimeType": item.mime_type,
                "byteSize": item.byte_size, "width": item.width, "height": item.height,
                "url": f"/api/customer/attachments/{item.attachment_id}/content",
            }
            for item in attachments
        ],
    )
    if created:
        repo.link_attachments([item.attachment_id for item in attachments], row.message_id)
        AuditRecorder(session).record(
            AuditContext.new_turn(actor_type="operator", conversation_id=conversation_id),
            event_type="operator_message",
            input_text=body,
            detail={"messageId": row.message_id},
        )
        from app.domain.consumer_service.risk_rules import evaluate_risks

        evaluate_risks(session)
    return message_view(row)


def assistant_input_hash(session: Session, conversation_id: str, *, sources=None) -> str:
    from app.config import get_settings
    from app.domain.consumer_service.grounding import WORKFLOW_VERSION, collect_sources, source_hash
    from app.domain.consumer_service.risk_rules import RULE_VERSION
    from app.domain.platform.settings import VISION_MODEL_KEY, get_enabled_template, get_setting

    template = get_enabled_template(session, "LOREAL_ASSISTANT")
    safety = get_enabled_template(session, "LOREAL_SAFETY")
    automatic = get_enabled_template(session, "LOREAL_AUTO_REPLY")
    from app.knowledge.repository import KnowledgeRepository

    snapshot = KnowledgeRepository(session).get_active_snapshot()
    from app.knowledge.models import KnowledgeDocumentRow

    conversation = session.get(ConversationRow, conversation_id)
    risk_settings = get_settings()
    # AI delivery also increments message_revision, but it is not new human
    # input and must not make the result that produced it stale.
    human_message_revision = session.scalar(
        select(func.max(MessageRow.applies_to_message_revision)).where(
            MessageRow.conversation_id == conversation_id,
            MessageRow.sender_role.in_(["customer", "operator"]),
        )
    ) or 0
    payload = {
        "workflow": WORKFLOW_VERSION,
        "visionModel": get_setting(session, VISION_MODEL_KEY) or get_settings().llm_vision_model,
        "riskRuleVersion": RULE_VERSION,
        "riskThresholds": (
            risk_settings.risk_response_wait_seconds, risk_settings.risk_followup_warning_minutes,
            risk_settings.risk_repeat_contact_hours, risk_settings.risk_source_ticket_hours,
        ),
        "sources": source_hash(sources if sources is not None else collect_sources(session, conversation_id)),
        "conversationRevision": (human_message_revision, conversation.mode_revision)
        if conversation else None,
        "prompt": (template.template_id, template.revision) if template else None,
        "safety": (safety.template_id, safety.revision) if safety else None,
        "automatic": (automatic.template_id, automatic.revision) if automatic else None,
        "knowledge": snapshot.snapshot_id if snapshot else None,
        "knowledgeDocuments": [
            (row.document_pk, row.enabled) for row in session.scalars(
                select(KnowledgeDocumentRow).where(
                    KnowledgeDocumentRow.knowledge_base_id.like("loreal-%"),
                ).order_by(KnowledgeDocumentRow.document_pk)
            )
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def service_history(session: Session, conversation_id: str) -> list[dict]:
    context = ConsumerServiceRepository(session).context(conversation_id)
    related = list(dict.fromkeys([
        *[order.conversation_id for order in context.orders],
        *context.history_conversation_ids,
    ]))
    return [
        {
            "conversationId": cid,
            "messages": [m.dump() for m in conversation_messages(session, cid)[-24:]],
        }
        for cid in related[-8:] if cid != conversation_id
    ]


def list_source_work_orders(session: Session):
    batch = active_batch(session)
    if batch is None:
        return []
    return [
        _work_order_view(session, row)
        for row in session.scalars(
            select(WorkOrderRow)
            .where(WorkOrderRow.batch_id == batch)
            .order_by(WorkOrderRow.created_at.desc())
        )
    ]
