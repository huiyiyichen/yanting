"""消费者画像卡与承诺追踪（改进方案 P1-2）。

只读聚合，不调用模型：
- 身份：本地会话有显式客户 ID；官方会话按买家昵称聚合（标注 aggregation，不等于身份认证）。
- 时间因果：只统计查看时点（当前会话最后一条消息）及之前发生的会话、订单与承诺。
- 承诺：只取客服/AI 的实际发言且含唯一明确期限；无业务证据不标已兑现。
- 肤质与“已拒绝”：只来自消费者本人原话，带来源引用。

工作日只跳过周六、周日，不处理法定节假日（见运行手册）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.consumer_service.emotion import score_message
from app.schemas.base import ApiModel

CST = timezone(timedelta(hours=8))
WORKDAY = re.compile(r"(?<!\d)([1-9]\d?)\s*个?\s*工作日")
SPAN = re.compile(r"(?<!\d)([1-9]\d{0,2})\s*(小时|天)(?:内|之内|以内)")
DATE = re.compile(r"(?<!\d)(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})(?:日|号)?")
SKIN = re.compile(r"(混干皮|混油皮|混合偏干|混合偏油|混合皮|混合性皮肤|干皮|油皮|干性皮肤|油性皮肤|敏感肌|中性皮肤|中性皮)")
REJECT = re.compile(r"(?:不想再?|不要再?|不打算|拒绝|不用再?)([^，。！？,.!?]{1,16})")
LEVELS = {0: "calm", 1: "dissatisfied", 2: "angry"}
SERVICE_ROLES = {"operator", "assistant", "staff"}


@dataclass(frozen=True)
class PromiseStatement:
    source_ref: str
    role: str
    text: str
    at: datetime  # UTC


@dataclass(frozen=True)
class ExtractedPromise:
    text: str
    made_at: datetime
    due_at: datetime
    source_ref: str
    deadline: str = ""
    full_text: str = ""


CLAUSE_END = re.compile(r"[。！？!?；;~～\n]+")


def deadline_clause(text: str, deadline: str) -> str:
    """只截取含期限的分句（全景方案 4.7）；找不到时退回整句截断。"""
    for clause in CLAUSE_END.split(text):
        if deadline and deadline in clause:
            return _sentence(clause.strip(" ，,"))
    return _sentence(text)


def workday_deadline(made_at: datetime, days: int) -> datetime:
    """发言次日起跳过周六、周日计数，到第 N 个工作日 23:59:59（UTC+8），返回 UTC。"""
    local = made_at.astimezone(CST).date()
    counted = 0
    while counted < days:
        local += timedelta(days=1)
        if local.weekday() < 5:
            counted += 1
    return datetime(local.year, local.month, local.day, 23, 59, 59, tzinfo=CST).astimezone(UTC)


def extract_promise(statement: PromiseStatement) -> ExtractedPromise | None:
    if statement.role not in SERVICE_ROLES or not statement.text:
        return None
    text = statement.text
    workdays = WORKDAY.findall(text)
    stripped = WORKDAY.sub("", text)
    spans, dates = SPAN.findall(stripped), DATE.findall(stripped)
    if len(workdays) + len(spans) + len(dates) != 1:
        return None
    match = WORKDAY.search(text) or SPAN.search(stripped) or DATE.search(stripped)
    deadline = match.group(0) if match else ""
    if workdays:
        due = workday_deadline(statement.at, int(workdays[0]))
    elif spans:
        amount, unit = spans[0]
        hours = int(amount) * (24 if unit == "天" else 1)
        if hours > 720:
            return None
        due = statement.at + timedelta(hours=hours)
    else:
        try:
            year, month, day = (int(value) for value in dates[0])
            due = datetime(year, month, day, 23, 59, 59, tzinfo=CST).astimezone(UTC)
        except ValueError:
            return None
    return ExtractedPromise(text=deadline_clause(text, deadline), made_at=statement.at, due_at=due,
                            source_ref=statement.source_ref, deadline=deadline, full_text=text)


def promise_status(due_at: datetime, *, as_of: datetime, evidence: str | None) -> str:
    if evidence:
        return "fulfilled"
    return "pending" if as_of < due_at else "due"


def self_reported_skin(messages: list[tuple[str, str, str]]) -> dict | None:
    """消费者本人自述的最新肤质；客服/AI 发言不计。"""
    found = None
    for role, ref, body in messages:
        if role != "customer" or not body:
            continue
        hits = SKIN.findall(body)
        if hits:
            found = {"text": hits[-1], "sourceRef": ref, "quote": _sentence(body)}
    return found


def _sentence(text: str, limit: int = 80) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _utc(value: datetime | None, *, imported: bool) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=CST if imported else UTC)
    return value.astimezone(UTC)


class ProfileItem(ApiModel):
    text: str
    source_ref: str


class ProfileSkin(ApiModel):
    text: str
    source_ref: str
    quote: str


class ProfileContacts(ApiModel):
    within_three_days: int
    total: int


class ProfileLastContact(ApiModel):
    conversation_id: str
    at: datetime
    scene: str


class ProfileMemory(ApiModel):
    concerns: list[ProfileItem]
    rejected: list[ProfileItem]
    tried: list[ProfileItem]
    pending: list[ProfileItem]


class ProfilePromise(ApiModel):
    text: str
    #: 期限原文（“3个工作日”），界面加粗；full_text 为整句，放悬停
    deadline: str = ""
    full_text: str = ""
    made_at: datetime
    due_at: datetime
    status: str
    source_ref: str
    evidence_ref: str | None = None


class ProfilePurchase(ApiModel):
    product: str
    order_id: str
    at: datetime


class EmotionPoint(ApiModel):
    at: datetime
    role: str
    level: str | None
    source_ref: str


class ConsumerProfileView(ApiModel):
    conversation_id: str
    alias: str
    aggregation: str
    as_of: datetime
    contacts: ProfileContacts
    last_contact: ProfileLastContact | None
    skin: ProfileSkin | None
    memory: ProfileMemory
    promises: list[ProfilePromise]
    purchases: list[ProfilePurchase]
    current_emotion: str | None
    escalated_at: datetime | None
    emotion_trail: list[EmotionPoint]


@dataclass
class _Conversation:
    conversation_id: str
    first_at: datetime
    last_at: datetime
    messages: list[tuple[str, str, str, datetime]]  # role, ref, body, at
    scene: str


def _imported(session: Session, batch: str | None, alias: str) -> list[_Conversation]:
    from app.domain.consumer_service.models import ServiceMessageRow

    if not batch or not alias:
        return []
    grouped: dict[str, list[ServiceMessageRow]] = {}
    for row in session.scalars(select(ServiceMessageRow).where(
        ServiceMessageRow.batch_id == batch, ServiceMessageRow.buyer_alias == alias,
    ).order_by(ServiceMessageRow.sent_at, ServiceMessageRow.sequence)):
        grouped.setdefault(row.conversation_id, []).append(row)
    result = []
    for cid, rows in grouped.items():
        messages = [(row.sender_role, f"message:{cid}:{row.message_id}", row.body or "",
                     _utc(row.sent_at, imported=True)) for row in rows]
        scene = next((row.scene_minor or row.scene_major for row in rows
                      if row.sender_role == "customer" and (row.scene_minor or row.scene_major)), "")
        result.append(_Conversation(cid, messages[0][3], messages[-1][3], messages, scene or ""))
    return result


def _local(session: Session, customer_id: str) -> list[_Conversation]:
    from app.domain.case_state.models import ConversationRow, MessageRow

    result = []
    for conversation in session.scalars(select(ConversationRow).where(ConversationRow.customer_id == customer_id)):
        rows = list(session.scalars(select(MessageRow).where(
            MessageRow.conversation_id == conversation.conversation_id).order_by(MessageRow.created_at)))
        if not rows:
            continue
        cid = conversation.conversation_id
        messages = [(row.sender_role, f"message:{cid}:{row.message_id}", row.body or "",
                     _utc(row.created_at, imported=False)) for row in rows]
        result.append(_Conversation(cid, messages[0][3], messages[-1][3], messages, conversation.title or ""))
    return result


def _memory(session: Session, conversation_ids: list[str]) -> dict[str, list[ProfileItem]]:
    from app.domain.consumer_service.models import ServiceMemoryRow

    buckets: dict[str, list[ProfileItem]] = {"concern": [], "attempted": [], "unresolved": []}
    for row in session.scalars(select(ServiceMemoryRow).where(ServiceMemoryRow.conversation_id.in_(conversation_ids))):
        for item in json.loads(row.payload_json):
            category = item.get("category")
            if category in buckets:
                text = item.get("label") or item.get("quote", "")
                ref = item.get("sourceRef") or item.get("source_ref", "")
                if text and ref and all(existing.text != text for existing in buckets[category]):
                    buckets[category].append(ProfileItem(text=_sentence(text, 40), source_ref=ref))
    return buckets


def build_consumer_profile(session: Session, conversation_id: str) -> ConsumerProfileView | None:
    from app.domain.case_state.models import ConversationRow
    from app.domain.consumer_service.models import (
        ServiceConversationRow,
        ServiceOrderRow,
        WorkOrderRow,
    )
    from app.domain.consumer_service.workspace import active_batch

    batch = active_batch(session)
    local = session.get(ConversationRow, conversation_id)
    if local is not None:
        alias, aggregation = local.customer_id, "customer_id"
    else:
        source = session.scalar(select(ServiceConversationRow).where(
            ServiceConversationRow.batch_id == batch,
            ServiceConversationRow.conversation_id == conversation_id,
        )) if batch else None
        if source is None:
            return None
        alias, aggregation = source.buyer_alias or "", "buyer_alias"

    conversations = {c.conversation_id: c for c in [*_imported(session, batch, alias), *_local(session, alias)]}
    current = conversations.get(conversation_id)
    if current is None:
        return None
    as_of = current.last_at
    visible = sorted((c for c in conversations.values() if c.first_at <= as_of), key=lambda c: c.first_at)
    previous = [c for c in visible if c.conversation_id != conversation_id]
    last_contact = previous[-1] if previous else None

    messages = [m for c in visible for m in c.messages if m[3] <= as_of]
    skin = self_reported_skin([(role, ref, body) for role, ref, body, _ in messages])
    rejected: list[ProfileItem] = []
    for role, ref, body, _ in messages:
        if role != "customer":
            continue
        for match in REJECT.finditer(body):
            text = match.group(0)
            if all(item.text != text for item in rejected):
                rejected.append(ProfileItem(text=text, source_ref=ref))

    payments = list(session.scalars(select(WorkOrderRow).where(
        WorkOrderRow.batch_id == batch, WorkOrderRow.buyer_alias == alias,
        WorkOrderRow.work_order_type == "offline_payment",
        WorkOrderRow.normalized_status == "completed",
    ))) if batch and aggregation == "buyer_alias" else []
    promises = []
    for role, ref, body, at in messages:
        promise = extract_promise(PromiseStatement(source_ref=ref, role=role, text=body, at=at))
        if promise is None:
            continue
        evidence = next((f"work_order:{row.work_order_id}" for row in payments
                         if (done := _utc(row.completed_at, imported=True)) and promise.made_at <= done <= as_of
                         and "打款" in promise.text), None)
        promises.append(ProfilePromise(
            text=promise.text, deadline=promise.deadline, full_text=promise.full_text,
            made_at=promise.made_at, due_at=promise.due_at,
            status=promise_status(promise.due_at, as_of=as_of, evidence=evidence),
            source_ref=promise.source_ref, evidence_ref=evidence,
        ))

    purchases = []
    if batch and aggregation == "buyer_alias":
        for order in session.scalars(select(ServiceOrderRow).where(
            ServiceOrderRow.batch_id == batch, ServiceOrderRow.buyer_alias == alias,
        ).order_by(ServiceOrderRow.ordered_at)):
            at = _utc(order.ordered_at, imported=True)
            if at <= as_of:
                purchases.append(ProfilePurchase(product=order.product_name or order.sku or "",
                                                 order_id=order.order_id, at=at))

    memory = _memory(session, [c.conversation_id for c in visible])
    trail, escalated_at, previous_level = [], None, None
    for role, ref, body, at in current.messages:
        if role in {"system"}:
            continue
        level = LEVELS.get(score_message(body)) if role == "customer" and body else None
        trail.append(EmotionPoint(at=at, role=role, level=level, source_ref=ref))
        if role == "customer" and level:
            if level == "angry" and previous_level in {"calm", "dissatisfied"}:
                escalated_at = escalated_at or at
            previous_level = level
    customer_levels = [point.level for point in trail if point.role == "customer" and point.level]
    return ConsumerProfileView(
        conversation_id=conversation_id, alias=alias, aggregation=aggregation, as_of=as_of,
        contacts=ProfileContacts(
            within_three_days=sum(1 for c in visible if as_of - c.first_at <= timedelta(hours=72)
                          or as_of - c.last_at <= timedelta(hours=72)),
            total=len(visible),
        ),
        last_contact=ProfileLastContact(conversation_id=last_contact.conversation_id,
                                        at=last_contact.last_at, scene=last_contact.scene)
        if last_contact else None,
        skin=ProfileSkin(text=skin["text"], source_ref=skin["sourceRef"], quote=skin["quote"]) if skin else None,
        memory=ProfileMemory(concerns=memory["concern"], rejected=rejected,
                             tried=memory["attempted"], pending=memory["unresolved"]),
        promises=promises, purchases=purchases,
        current_emotion=customer_levels[-1] if customer_levels else None,
        escalated_at=escalated_at, emotion_trail=trail,
    )
