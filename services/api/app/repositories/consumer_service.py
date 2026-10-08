"""Read-only queries for the imported consumer-service facts."""

from __future__ import annotations

import json
from typing import Any

from pydantic.alias_generators import to_camel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.consumer_service.mapping import DATASET_ID
from app.domain.consumer_service.models import (
    DETAIL_MODELS,
    DatasetRow,
    ImportBatchRow,
    ServiceConversationRow,
    ServiceEventRow,
    ServiceMessageRow,
    ServiceOrderRow,
    WorkOrderRow,
)
from app.domain.enums import ServiceMode
from app.errors import NotFoundError
from app.schemas.consumer_service import (
    ConsumerHistoryView,
    ConsumerServiceContextView,
    ServiceMessageView,
    ServiceNodeView,
    ServiceOrderView,
    ServiceProductView,
    ServiceTimelineEventView,
    ServiceWorkOrderView,
)
from app.schemas.conversation import QueueItem


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _detail(session: Session, row: WorkOrderRow) -> dict[str, Any]:
    detail_model = DETAIL_MODELS.get(row.work_order_type)
    if detail_model is None:
        return {}
    detail = session.get(detail_model, row.record_id)
    if detail is None:
        return {}
    try:
        value = json.loads(detail.fields_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return _camelize(value) if isinstance(value, dict) else {}


def _camelize(value: Any) -> Any:
    if isinstance(value, dict):
        return {to_camel(str(key)): _camelize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    return value


def _order_view(row: ServiceOrderRow) -> ServiceOrderView:
    return ServiceOrderView(
        source_record_id=row.source_record_id,
        order_id=row.order_id,
        conversation_id=row.conversation_id,
        buyer_alias=row.buyer_alias,
        sku=row.sku,
        product_name=row.product_name,
        quantity=row.quantity,
        unit_price_minor=row.unit_price_minor,
        paid_amount_minor=row.paid_amount_minor,
        currency=row.currency,
        source_status=row.source_status,
        ordered_at=row.ordered_at.isoformat(),
        paid_at=_iso(row.paid_at),
        shipped_at=_iso(row.shipped_at),
        carrier=row.carrier,
        tracking_no=row.tracking_no,
        province=row.province,
        city=row.city,
        gift=row.gift,
        buyer_note=row.buyer_note,
    )


def _work_order_view(session: Session, row: WorkOrderRow) -> ServiceWorkOrderView:
    return ServiceWorkOrderView(
        source_record_id=row.source_record_id,
        work_order_id=row.work_order_id,
        work_order_type=row.work_order_type,
        conversation_id=row.conversation_id,
        buyer_alias=row.buyer_alias,
        order_id=row.order_id,
        source_status=row.source_status,
        normalized_status=row.normalized_status,
        handler=row.handler,
        created_at=row.created_at.isoformat(),
        completed_at=_iso(row.completed_at),
        detail=_detail(session, row),
    )


def _message_view(row: ServiceMessageRow) -> ServiceMessageView:
    return ServiceMessageView(
        source_record_id=row.source_record_id,
        message_id=row.message_id,
        conversation_id=row.conversation_id,
        sender_role=row.sender_role,
        sender=row.sender,
        body=row.body,
        content_type=row.content_type,
        image_ref=row.image_ref,
        order_id=row.order_id,
        work_order_id=row.work_order_id,
    )


class ConsumerServiceRepository:
    """读取当前发布批次，不写入导入事实。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def queue(self) -> list[QueueItem]:
        dataset = self._session.get(DatasetRow, DATASET_ID)
        if dataset is None:
            return []
        batch = self._session.get(ImportBatchRow, dataset.active_batch_id)
        if batch is None:
            return []
        rows = list(
            self._session.scalars(
                select(ServiceConversationRow)
                .where(ServiceConversationRow.batch_id == batch.batch_id)
                .order_by(
                    ServiceConversationRow.last_at.desc(),
                    ServiceConversationRow.conversation_id.asc(),
                )
            )
        )
        return [
            QueueItem(
                conversation_id=row.conversation_id,
                title=row.buyer_alias or row.conversation_id,
                customer_id=row.buyer_alias or row.conversation_id,
                service_mode=ServiceMode.AUTONOMOUS,
                updated_at=(_iso(row.last_at) or _iso(row.first_at) or ""),
                data_source="imported",
            )
            for row in rows
        ]

    def context(self, conversation_id: str) -> ConsumerServiceContextView:
        from app.domain.case_state.models import ConversationRow

        local = self._session.get(ConversationRow, conversation_id)
        dataset = self._session.get(DatasetRow, DATASET_ID)
        if dataset is None:
            if local is not None:
                return self._local_context(local, None)
            raise NotFoundError("尚未发布业务数据")
        batch = self._session.get(ImportBatchRow, dataset.active_batch_id)
        if batch is None:
            raise NotFoundError("业务数据批次不存在")

        conversation = self._session.scalar(
            select(ServiceConversationRow).where(
                ServiceConversationRow.batch_id == batch.batch_id,
                ServiceConversationRow.conversation_id == conversation_id,
            )
        )
        if conversation is None:
            if local is not None:
                return self._local_context(local, batch.batch_id)
            raise NotFoundError(f"业务数据中不存在会话：{conversation_id}")

        orders = list(
            self._session.scalars(
                select(ServiceOrderRow)
                .where(
                    ServiceOrderRow.batch_id == batch.batch_id,
                    ServiceOrderRow.conversation_record_id == conversation.record_id,
                )
                .order_by(ServiceOrderRow.ordered_at.asc(), ServiceOrderRow.order_id.asc())
            )
        )
        work_orders = list(
            self._session.scalars(
                select(WorkOrderRow)
                .where(
                    WorkOrderRow.batch_id == batch.batch_id,
                    WorkOrderRow.conversation_record_id == conversation.record_id,
                )
                .order_by(WorkOrderRow.created_at.asc(), WorkOrderRow.work_order_id.asc())
            )
        )
        messages = list(
            self._session.scalars(
                select(ServiceMessageRow)
                .where(
                    ServiceMessageRow.batch_id == batch.batch_id,
                    ServiceMessageRow.conversation_record_id == conversation.record_id,
                )
                .order_by(ServiceMessageRow.sent_at.asc(), ServiceMessageRow.sequence.asc())
            )
        )
        event_rows = list(
            self._session.scalars(
                select(ServiceEventRow)
                .where(
                    ServiceEventRow.batch_id == batch.batch_id,
                    ServiceEventRow.conversation_record_id == conversation.record_id,
                )
                .order_by(ServiceEventRow.occurred_at.asc(), ServiceEventRow.event_id.asc())
            )
        )

        orders_by_record = {row.record_id: _order_view(row) for row in orders}
        work_orders_by_record = {
            row.record_id: _work_order_view(self._session, row) for row in work_orders
        }
        messages_by_record = {row.record_id: _message_view(row) for row in messages}
        timeline: list[ServiceTimelineEventView] = []
        for event in event_rows:
            timeline.append(
                ServiceTimelineEventView(
                    event_id=event.event_id,
                    source_record_id=event.source_record_id,
                    entity_type=event.entity_type,
                    event_type=event.event_type,
                    occurred_at=event.occurred_at.isoformat(),
                    message=(
                        messages_by_record.get(event.entity_record_id)
                        if event.entity_type == "message"
                        else None
                    ),
                    order=(
                        orders_by_record.get(event.entity_record_id)
                        if event.entity_type == "order"
                        else None
                    ),
                    work_order=(
                        work_orders_by_record.get(event.entity_record_id)
                        if event.entity_type == "work_order"
                        else None
                    ),
                )
            )

        context = ConsumerServiceContextView(
            dataset_id=DATASET_ID,
            batch_id=batch.batch_id,
            conversation_id=conversation.conversation_id,
            buyer_alias=conversation.buyer_alias,
            buyer_aliases=json.loads(conversation.aliases_json or "[]"),
            first_at=_iso(conversation.first_at),
            last_at=_iso(conversation.last_at),
            orders=[orders_by_record[row.record_id] for row in orders],
            work_orders=[work_orders_by_record[row.record_id] for row in work_orders],
            timeline=timeline,
        )
        self._enrich(context, batch.batch_id)
        return context

    def _local_context(self, local: Any, batch_id: str | None) -> ConsumerServiceContextView:
        from app.domain.case_state.models import MessageRow

        messages = list(
            self._session.scalars(
                select(MessageRow)
                .where(
                    MessageRow.conversation_id == local.conversation_id,
                )
                .order_by(MessageRow.applies_to_message_revision)
            )
        )
        context = ConsumerServiceContextView(
            dataset_id=DATASET_ID,
            batch_id=batch_id or "local",
            conversation_id=local.conversation_id,
            buyer_alias=local.customer_id,
            buyer_aliases=[local.customer_id],
            first_at=_iso(local.created_at),
            last_at=_iso(local.updated_at),
            orders=[],
            work_orders=[],
            timeline=[
                ServiceTimelineEventView(
                    event_id=row.message_id,
                    source_record_id=row.message_id,
                    entity_type="message",
                    event_type="message",
                    occurred_at=_iso(row.created_at),
                    message=ServiceMessageView(
                        source_record_id=row.message_id,
                        message_id=row.message_id,
                        conversation_id=row.conversation_id,
                        sender_role=row.sender_role,
                        body=row.body,
                        content_type="image" if json.loads(row.attachments_json) else "text",
                    ),
                )
                for row in messages
            ],
        )
        # Explicit order numbers in the customer's messages are exact links, never fuzzy identity matches.
        text = " ".join(row.body for row in messages if row.sender_role == "customer")
        orders = list(
            self._session.scalars(
                select(ServiceOrderRow).where(ServiceOrderRow.batch_id == batch_id)
            )
        )
        context.orders = [_order_view(row) for row in orders if row.order_id in text]
        if context.orders:
            context.work_orders = [
                _work_order_view(self._session, row)
                for row in self._session.scalars(
                    select(WorkOrderRow).where(
                        WorkOrderRow.batch_id == batch_id,
                        WorkOrderRow.order_id.in_([order.order_id for order in context.orders]),
                    )
                )
            ]
        self._enrich(context, batch_id)
        return context

    def _enrich(self, context: ConsumerServiceContextView, batch_id: str | None) -> None:
        products: dict[str, ServiceProductView] = {}
        for order in context.orders:
            if order.product_name:
                products[order.product_name] = ServiceProductView(
                    sku=order.sku,
                    name=order.product_name,
                    unit_price_minor=order.unit_price_minor,
                    source_record_ids=[order.source_record_id],
                )
        text = " ".join(event.message.body or "" for event in context.timeline if event.message)
        for row in self._session.scalars(
            select(ServiceOrderRow).where(ServiceOrderRow.batch_id == batch_id)
        ):
            if row.product_name and row.product_name in text and row.product_name not in products:
                products[row.product_name] = ServiceProductView(
                    sku=row.sku,
                    name=row.product_name,
                    unit_price_minor=row.unit_price_minor,
                    source_record_ids=[row.source_record_id],
                )
        context.products = list(products.values())
        nodes: list[ServiceNodeView] = []
        for order in context.orders:
            for kind, time in [
                ("下单", order.ordered_at),
                ("付款", order.paid_at),
                ("发货", order.shipped_at),
            ]:
                if time:
                    nodes.append(
                        ServiceNodeView(
                            occurred_at=time,
                            kind=kind,
                            title=order.order_id,
                            status=order.source_status if kind == "下单" else None,
                            source_record_id=order.source_record_id,
                        )
                    )
        for work in context.work_orders:
            nodes.append(
                ServiceNodeView(
                    occurred_at=work.created_at,
                    kind="工单创建",
                    title=work.work_order_id,
                    status=work.source_status,
                    source_record_id=work.source_record_id,
                )
            )
            if work.completed_at:
                nodes.append(
                    ServiceNodeView(
                        occurred_at=work.completed_at,
                        kind="工单完结",
                        title=work.work_order_id,
                        status=work.source_status,
                        source_record_id=work.source_record_id,
                    )
                )
        history = list(
            self._session.scalars(
                select(ServiceConversationRow)
                .where(
                    ServiceConversationRow.batch_id == batch_id,
                    ServiceConversationRow.buyer_alias == context.buyer_alias,
                    ServiceConversationRow.conversation_id != context.conversation_id,
                )
                .order_by(ServiceConversationRow.first_at)
            )
        )
        context.history_conversation_ids = [row.conversation_id for row in history]
        current_orders = {order.order_id for order in context.orders}
        current_messages = list(self._session.scalars(
            select(ServiceMessageRow).where(
                ServiceMessageRow.batch_id == batch_id,
                ServiceMessageRow.conversation_id == context.conversation_id,
            )
        ))
        current_topics = {
            f"{item.scene_major or ''}|{item.scene_minor or ''}"
            for item in current_messages
            if item.sender_role == "customer" and (item.scene_major or item.scene_minor)
        }
        history_services: list[ConsumerHistoryView] = []
        for row in history:
            history_messages = list(self._session.scalars(
                select(ServiceMessageRow)
                .where(
                    ServiceMessageRow.batch_id == batch_id,
                    ServiceMessageRow.conversation_id == row.conversation_id,
                )
                .order_by(ServiceMessageRow.sent_at.asc(), ServiceMessageRow.sequence.asc())
            ))
            history_orders = list(self._session.scalars(
                select(ServiceOrderRow).where(
                    ServiceOrderRow.batch_id == batch_id,
                    ServiceOrderRow.conversation_id == row.conversation_id,
                )
            ))
            history_work_orders = list(self._session.scalars(
                select(WorkOrderRow).where(
                    WorkOrderRow.batch_id == batch_id,
                    WorkOrderRow.conversation_id == row.conversation_id,
                )
            ))
            history_topics = {
                f"{item.scene_major or ''}|{item.scene_minor or ''}"
                for item in history_messages
                if item.sender_role == "customer" and (item.scene_major or item.scene_minor)
            }
            history_services.append(ConsumerHistoryView(
                conversation_id=row.conversation_id,
                first_at=_iso(row.first_at),
                last_at=_iso(row.last_at),
                latest_customer_message=next(
                    (item.body or "" for item in reversed(history_messages)
                     if item.sender_role == "customer"), "",
                ),
                latest_staff_message=next(
                    (item.body or "" for item in reversed(history_messages)
                     if item.sender_role in {"staff", "operator", "assistant"}), "",
                ),
                order_ids=[item.order_id for item in history_orders],
                work_order_ids=[item.work_order_id for item in history_work_orders],
                relation="same_order" if current_orders.intersection(
                    item.order_id for item in history_orders
                ) else "historical",
                same_topic=(
                    bool(current_topics.intersection(history_topics))
                    if current_topics and history_topics else None
                ),
            ))
            if row.last_at:
                nodes.append(
                    ServiceNodeView(
                        occurred_at=row.last_at.isoformat(),
                        kind="历史进线",
                        title=row.conversation_id,
                        source_record_id=row.record_id,
                    )
                )
        context.service_nodes = sorted(nodes, key=lambda item: item.occurred_at)
        context.history_services = sorted(
            history_services,
            key=lambda item: item.last_at or item.first_at or "",
            reverse=True,
        )
