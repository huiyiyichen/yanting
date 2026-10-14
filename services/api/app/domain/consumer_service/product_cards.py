"""商品卡（P1-4）：客户可选商品、发送时服务端解析、客服顶部商品卡。

客户侧只拿商品身份（SKU、名称、公开商品图、自己报过的订单号）；实付、状态、
物流等事实只在客服侧商品卡出现，且全部取自官方订单原值。
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.case_state.models import MessageRow
from app.errors import NotFoundError, ValidationRejected
from app.knowledge.models import KnowledgeReferenceProductRow
from app.repositories.consumer_service import ConsumerServiceRepository
from app.schemas.base import ApiModel
from app.schemas.consumer_service import ServiceOrderView
from app.schemas.conversation import ProductCardView, ProductRef


class DeskProductCardView(ApiModel):
    """客服聊天区顶部商品卡。source=message 表示来自消费者最新发送的商品卡。"""

    source: str
    sku: str | None = None
    name: str
    image_url: str | None = None
    order_id: str | None = None
    paid_amount_minor: int | None = None
    currency: str | None = None
    status: str | None = None
    carrier: str | None = None
    city: str | None = None


def catalog(session: Session) -> list[dict]:
    rows = session.scalars(select(KnowledgeReferenceProductRow).order_by(KnowledgeReferenceProductRow.product_id))
    return [json.loads(row.payload_json) | {"sku": row.product_id} for row in rows]


def linked_orders(session: Session, conversation_id: str) -> list[ServiceOrderView]:
    try:
        orders = ConsumerServiceRepository(session).context(conversation_id).orders
    except NotFoundError:
        return []
    return sorted(orders, key=lambda order: order.ordered_at, reverse=True)


def _image_for(session: Session, sku: str | None) -> str | None:
    return next((item.get("image_url") for item in catalog(session) if sku and item["sku"] == sku), None)


def customer_options(session: Session, conversation_id: str) -> list[ProductCardView]:
    orders = [
        ProductCardView(source="order", sku=order.sku, name=order.product_name or order.order_id,
                        image_url=_image_for(session, order.sku), order_id=order.order_id)
        for order in linked_orders(session, conversation_id)
    ]
    products = [
        ProductCardView(source="catalog", sku=item["sku"], name=item["name"], image_url=item.get("image_url"))
        for item in catalog(session)
    ]
    return orders + products


def resolve(session: Session, conversation_id: str, ref: ProductRef) -> ProductCardView:
    if ref.order_id:
        order = next((o for o in linked_orders(session, conversation_id) if o.order_id == ref.order_id), None)
        if order is None:
            raise ValidationRejected("订单不属于当前会话")
        return ProductCardView(source="order", sku=order.sku, name=order.product_name or order.order_id,
                               image_url=_image_for(session, order.sku), order_id=order.order_id)
    if ref.sku:
        item = next((i for i in catalog(session) if i["sku"] == ref.sku), None)
        if item is None:
            raise ValidationRejected("商品不存在")
        return ProductCardView(source="catalog", sku=item["sku"], name=item["name"], image_url=item.get("image_url"))
    raise ValidationRejected("请选择商品")


def card_text(card: dict) -> str:
    """Agent 上下文里的商品卡文本：消费者正在咨询的商品。"""
    order = f"，订单号 {card['orderId']}" if card.get("orderId") else ""
    return f"[商品卡] {card.get('name')}（{card.get('sku') or '无货号'}{order}）"


def desk_card(session: Session, conversation_id: str) -> DeskProductCardView | None:
    orders = linked_orders(session, conversation_id)
    latest = session.scalars(
        select(MessageRow).where(MessageRow.conversation_id == conversation_id,
                                 MessageRow.product_card_json.is_not(None))
        .order_by(MessageRow.created_at.desc(), MessageRow.applies_to_message_revision.desc())
    ).first()
    if latest is not None:
        card = json.loads(latest.product_card_json)
        order = next((o for o in orders if card.get("orderId") and o.order_id == card["orderId"]), None)
        return _desk_view("message", card.get("sku"), card["name"], card.get("imageUrl"), order)
    if orders:
        order = orders[0]
        return _desk_view("order", order.sku, order.product_name or order.order_id, _image_for(session, order.sku), order)
    return None


def _desk_view(source, sku, name, image_url, order: ServiceOrderView | None) -> DeskProductCardView:
    return DeskProductCardView(
        source=source, sku=sku, name=name, image_url=image_url,
        order_id=order.order_id if order else None,
        paid_amount_minor=order.paid_amount_minor if order else None,
        currency=order.currency if order else None,
        status=order.source_status if order else None,
        carrier=order.carrier if order else None,
        city=order.city if order else None,
    )
