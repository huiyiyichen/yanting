from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditContext, AuditRecorder
from app.domain.consumer_service.models import (
    ServiceDeskEventRow,
    ServiceTicketDetailRow,
    ServiceTicketRow,
    WorkOrderRow,
)
from app.domain.consumer_service.operators import DEFAULT_OPERATOR
from app.domain.consumer_service.workspace import active_batch
from app.errors import ConflictError, NotFoundError, ValidationRejected
from app.repositories.consumer_service import ConsumerServiceRepository, _detail
from app.schemas.service_desk import (
    TicketCreateRequest,
    TicketDetail,
    TicketEventView,
    TicketUpdateRequest,
    TicketView,
)

TYPE_LABELS = {
    "reship_exchange": "补发换货",
    "offline_payment": "线下打款",
    "logistics": "物流",
    "adverse_reaction": "不良反应",
    "return_refund": "售后退货",
}


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def deadline(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("missing timezone")
        return parsed.astimezone(UTC).replace(tzinfo=None)
    except ValueError as exc:
        raise ValidationRejected("跟进时间必须包含时区") from exc


def event_view(row: ServiceDeskEventRow) -> TicketEventView:
    return TicketEventView(
        event_id=row.event_id, actor=row.actor, action=row.action, note=row.note,
        created_at=row.created_at.replace(tzinfo=UTC).isoformat(),
    )


def record_event(
    session: Session, entity_id: str, kind: str, action: str, note: str,
    conversation_id: str | None = None,
    *, actor: str = DEFAULT_OPERATOR,
) -> None:
    session.add(ServiceDeskEventRow(
        event_id=f"desk-{uuid4().hex[:16]}", entity_id=entity_id, entity_kind=kind,
        actor=actor, action=action, note=note.strip(),
    ))
    AuditRecorder(session).record(
        AuditContext.new_turn(actor_type="operator", conversation_id=conversation_id),
        event_type=f"{kind}_updated",
        detail={"entityId": entity_id, "action": action, "operatorId": actor, "note": note.strip()[:500]},
    )
    session.flush()


def events_for(session: Session, entity_id: str) -> list[TicketEventView]:
    return [event_view(row) for row in session.scalars(
        select(ServiceDeskEventRow).where(ServiceDeskEventRow.entity_id == entity_id)
        .order_by(ServiceDeskEventRow.created_at.desc(), ServiceDeskEventRow.event_id)
    )]


def _view(
    session: Session, source: WorkOrderRow | None, local: ServiceTicketRow | None,
    *, include_events: bool = False,
) -> TicketView:
    assert source is not None or local is not None
    ticket_id = local.ticket_id if local else source.work_order_id
    local_detail = session.get(ServiceTicketDetailRow, ticket_id)
    return TicketView(
        ticket_id=ticket_id,
        title=local.title if local else f"{TYPE_LABELS[source.work_order_type]} · {source.buyer_alias}",
        conversation_id=local.conversation_id if local else source.conversation_id,
        buyer_alias=local.buyer_alias if local else source.buyer_alias,
        order_id=local.order_id if local else source.order_id,
        work_order_type=local.work_order_type if local else source.work_order_type,
        source_status=source.source_status if source else None,
        source_record_id=source.source_record_id if source else None,
        status=local.status if local else (
            "resolved" if source.normalized_status == "completed" else "pending"
        ),
        priority=local.priority if local else (
            "high" if source.work_order_type == "adverse_reaction" else "normal"
        ),
        assignee=local.assignee if local else source.handler or "",
        due_at=local.due_at.replace(tzinfo=UTC).isoformat() if local and local.due_at else None,
        created_at=(source.created_at if source else local.created_at).isoformat(),
        updated_at=(local.updated_at.replace(tzinfo=UTC).isoformat() if local else
                    (source.completed_at or source.created_at).isoformat()),
        revision=local.revision if local else 0,
        detail=_detail(session, source) if source else {},
        local_detail=json.loads(local_detail.payload_json) if local_detail else None,
        events=events_for(session, ticket_id) if include_events else [],
    )


def list_tickets(
    session: Session, conversation_id: str | None = None, *, include_events: bool = False,
) -> list[TicketView]:
    batch = active_batch(session)
    sources = list(session.scalars(select(WorkOrderRow).where(WorkOrderRow.batch_id == batch)))
    locals_ = list(session.scalars(select(ServiceTicketRow)))
    by_source = {row.source_record_id: row for row in locals_ if row.source_record_id}
    items = [_view(session, row, by_source.get(row.source_record_id)) for row in sources]
    items.extend(_view(session, None, row) for row in locals_ if row.source_record_id is None)
    if conversation_id:
        context = ConsumerServiceRepository(session).context(conversation_id)
        order_ids = {row.order_id for row in context.orders}
        items = [item for item in items if item.conversation_id == conversation_id
                 or item.order_id in order_ids]
    if include_events:
        for item in items:
            item.events = events_for(session, item.ticket_id)
    return sorted(items, key=lambda item: item.updated_at, reverse=True)


def get_ticket(session: Session, ticket_id: str) -> TicketView:
    local = session.get(ServiceTicketRow, ticket_id)
    source = session.scalar(select(WorkOrderRow).where(
        WorkOrderRow.batch_id == active_batch(session), WorkOrderRow.work_order_id == ticket_id,
    ))
    if local is None and source is None:
        raise NotFoundError("工单不存在")
    return _view(session, source, local, include_events=True)


def _save_detail(session: Session, ticket_id: str, ticket_type: str, detail: TicketDetail | None) -> None:
    if detail is None:
        return
    if detail.kind != ticket_type:
        raise ValidationRejected("事项资料与工单类型不一致")
    row = session.get(ServiceTicketDetailRow, ticket_id)
    if row is None:
        row = ServiceTicketDetailRow(ticket_id=ticket_id)
        session.add(row)
    row.payload_json = detail.model_dump_json(by_alias=True)
    session.flush()


def _record_deadline_change(
    session: Session, row: ServiceTicketRow, previous: datetime | None, *, actor: str,
) -> None:
    if row.due_at == previous:
        return
    AuditRecorder(session).record(
        AuditContext.new_turn(actor_type="operator", conversation_id=row.conversation_id),
        event_type="ticket_deadline_changed",
        detail={
            "ticketId": row.ticket_id, "operatorId": actor,
            "previousDueAt": previous.replace(tzinfo=UTC).isoformat() if previous else None,
            "dueAt": row.due_at.replace(tzinfo=UTC).isoformat() if row.due_at else None,
        },
    )


def create_ticket(
    session: Session, payload: TicketCreateRequest, *, actor: str = DEFAULT_OPERATOR,
) -> TicketView:
    if not payload.title.strip() or not payload.note.strip():
        raise ValidationRejected("标题和事项说明不能为空")
    context = ConsumerServiceRepository(session).context(payload.conversation_id)
    if payload.order_id and payload.order_id not in {row.order_id for row in context.orders}:
        raise ValidationRejected("订单不属于当前会话关联范围")
    row = ServiceTicketRow(
        ticket_id=f"LOCAL-{uuid4().hex[:10].upper()}", title=payload.title.strip(),
        conversation_id=payload.conversation_id, buyer_alias=context.buyer_alias,
        order_id=payload.order_id, work_order_type=payload.work_order_type,
        priority=payload.priority, assignee=payload.assignee.strip(), due_at=deadline(payload.due_at),
    )
    session.add(row)
    session.flush()
    _save_detail(session, row.ticket_id, row.work_order_type, payload.local_detail)
    record_event(session, row.ticket_id, "ticket", "创建工单", payload.note, row.conversation_id, actor=actor)
    _record_deadline_change(session, row, None, actor=actor)
    from app.domain.consumer_service.risk_rules import evaluate_risks

    evaluate_risks(session)
    return get_ticket(session, row.ticket_id)


def update_ticket(
    session: Session, ticket_id: str, payload: TicketUpdateRequest, *, actor: str = DEFAULT_OPERATOR,
) -> TicketView:
    before = get_ticket(session, ticket_id)
    if before.revision != payload.expected_revision:
        raise ConflictError("工单已更新，请刷新后重试")
    if not payload.note.strip():
        raise ValidationRejected("请填写跟进记录")
    if before.status == "pending" and payload.status == "resolved":
        raise ValidationRejected("请先开始处理，再完成工单")
    if before.status == "resolved" and payload.status not in {"resolved", "in_progress"}:
        raise ValidationRejected("已完成工单只能重新打开为处理中")
    if payload.status != "pending" and not payload.assignee.strip():
        raise ValidationRejected("请指定负责人")
    row = session.get(ServiceTicketRow, ticket_id)
    if row is None:
        row = ServiceTicketRow(
            ticket_id=ticket_id, source_record_id=before.source_record_id,
            conversation_id=before.conversation_id, buyer_alias=before.buyer_alias,
            order_id=before.order_id, work_order_type=before.work_order_type,
            title=before.title, revision=0,
        )
        session.add(row)
    row.status = payload.status
    row.priority = payload.priority
    row.assignee = payload.assignee.strip()
    row.due_at = deadline(payload.due_at)
    row.revision += 1
    row.updated_at = now()
    session.flush()
    _save_detail(session, ticket_id, row.work_order_type, payload.local_detail)
    record_event(
        session, ticket_id, "ticket",
        f"{before.status} → {row.status} · {row.assignee or '待分配'}",
        payload.note, before.conversation_id, actor=actor,
    )
    _record_deadline_change(session, row, deadline(before.due_at), actor=actor)
    from app.domain.consumer_service.risk_rules import evaluate_risks

    evaluate_risks(session)
    return get_ticket(session, ticket_id)
