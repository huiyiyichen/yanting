"""风险看板总览与商品风险线索（改进方案 P1-6）。只读，不调用模型。

统计口径：
- 信号：逐条规则命中（service_risk_alert 每行一条）。
- 事件：按风险事件合并后的条数（incidents.list_incidents）。
- 范围：official = 官方导入会话；live = 客户页新建的本地会话。
- 情绪分布：消费者消息逐条按 emotion.py 规则判定（emotionSource=rule），UTC+8 每小时分桶，08–23 时。
- 商品线索：只给计数与原始记录入口，不给质量结论；批次“00”或空记为“未记录”。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.schemas.base import ApiModel

CST = timezone(timedelta(hours=8))
LEVELS = {0: "calm", 1: "dissatisfied", 2: "angry"}
UNRECORDED_BATCH = {"", "00", "0", "无", "未记录", "None"}
Scope = Literal["official", "live"]


class OverviewCounts(ApiModel):
    events: int
    signals: int
    pending: int
    pending_high: int = 0
    high: int
    emotion_escalation: int
    adverse_reaction: int


class HourBucket(ApiModel):
    date: str
    hour: int
    calm: int
    dissatisfied: int
    angry: int


class HighRiskMarker(ApiModel):
    date: str
    hour: int
    conversation_id: str
    alias: str
    types: list[str]


class RiskOverviewView(ApiModel):
    scope: Scope
    counts: OverviewCounts
    levels: dict[str, int]
    types: dict[str, int]
    hourly: list[HourBucket]
    high_risk_markers: list[HighRiskMarker]
    customer_messages: int
    negative_share: float
    emotion_source: Literal["rule"]
    # 指定 from/to 时：该时段内有消费者消息的会话（风险列表按它筛选）；未指定为 None
    range_conversation_ids: list[str] | None = None


class ProductClueCase(ApiModel):
    """商品线索的一条原始记录：工单 → 订单 → 会话（全景方案 5.4，反馈 ⑤）。"""

    work_order_id: str
    work_order_type: str
    order_id: str | None = None
    conversation_id: str
    buyer_alias: str
    batch: str | None = None
    created_at: str


class ProductClueView(ApiModel):
    product_name: str
    adverse_reactions: int
    medical_visits: int
    batches: list[str]
    related_tickets: int
    other_tickets: int
    abnormal_returns: int
    score: int
    work_order_ids: list[str]
    cases: list[ProductClueCase] = []


def _cst(value: datetime, *, imported: bool) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=CST if imported else UTC)
    return value.astimezone(CST)


def _customer_messages(session: Session, scope: Scope, batch: str | None) -> list[tuple[str, str, datetime]]:
    from app.domain.case_state.models import MessageRow
    from app.domain.consumer_service.models import ServiceMessageRow

    if scope == "official":
        if not batch:
            return []
        rows = session.execute(select(ServiceMessageRow.conversation_id, ServiceMessageRow.body,
                                      ServiceMessageRow.sent_at).where(
            ServiceMessageRow.batch_id == batch, ServiceMessageRow.sender_role == "customer"))
        return [(cid, body or "", _cst(at, imported=True)) for cid, body, at in rows if body]
    rows = session.execute(select(MessageRow.conversation_id, MessageRow.body, MessageRow.created_at).where(
        MessageRow.sender_role == "customer"))
    return [(cid, body or "", _cst(at, imported=False)) for cid, body, at in rows if body]


def _in_range(day: str, date_from: date | None, date_to: date | None) -> bool:
    return (date_from is None or day >= date_from.isoformat()) and (date_to is None or day <= date_to.isoformat())


def risk_overview(session: Session, scope: Scope, date_from: date | None = None,
                  date_to: date | None = None) -> RiskOverviewView:
    from app.domain.consumer_service.emotion import score_message
    from app.domain.consumer_service.incidents import is_pending, list_incidents
    from app.domain.consumer_service.models import ServiceConversationRow, ServiceRiskAlertRow
    from app.domain.consumer_service.workspace import active_batch

    batch = active_batch(session)
    imported = set(session.scalars(select(ServiceConversationRow.conversation_id).where(
        ServiceConversationRow.batch_id == batch))) if batch else set()

    def in_scope(conversation_id: str) -> bool:
        return (conversation_id in imported) == (scope == "official")

    messages = _customer_messages(session, scope, batch)
    ranged = date_from is not None or date_to is not None
    active = {cid for cid, _, at in messages if _in_range(at.date().isoformat(), date_from, date_to)}

    def in_view(conversation_id: str) -> bool:
        return in_scope(conversation_id) and (not ranged or conversation_id in active)

    alerts = [row for row in session.scalars(select(ServiceRiskAlertRow).where(
        ServiceRiskAlertRow.batch_id == batch)) if in_view(row.conversation_id)] if batch else []
    incidents = [item for item in list_incidents(session)
                 if item.conversation_ids and all(in_scope(cid) for cid in item.conversation_ids)
                 and (not ranged or any(cid in active for cid in item.conversation_ids))]

    buckets: dict[tuple[str, int], Counter] = defaultdict(Counter)
    last_message: dict[str, datetime] = {}
    for cid, body, at in messages:
        last_message[cid] = max(last_message.get(cid, at), at)
        if 8 <= at.hour <= 23:
            buckets[(at.date().isoformat(), at.hour)][LEVELS[score_message(body)]] += 1
    hourly = [HourBucket(date=day, hour=hour, calm=c["calm"], dissatisfied=c["dissatisfied"], angry=c["angry"])
              for (day, hour), c in sorted(buckets.items())]
    counted = sum(b.calm + b.dissatisfied + b.angry for b in hourly)
    negative = sum(b.dissatisfied + b.angry for b in hourly)

    high_types: dict[str, list[str]] = defaultdict(list)
    aliases: dict[str, str] = {}
    for row in alerts:
        if row.risk_level == "high":
            high_types[row.conversation_id].append(row.risk_type)
            aliases[row.conversation_id] = row.buyer_alias
    markers = []
    for cid, types in sorted(high_types.items()):
        at = last_message.get(cid)
        if at is not None:
            markers.append(HighRiskMarker(date=at.date().isoformat(), hour=at.hour, conversation_id=cid,
                                          alias=aliases[cid], types=sorted(set(types))))

    levels = Counter(row.risk_level for row in alerts)
    types = Counter(row.risk_type for row in alerts)
    return RiskOverviewView(
        scope=scope,
        counts=OverviewCounts(
            events=len(incidents), signals=len(alerts),
            pending=sum(1 for item in incidents if is_pending(item)),
            pending_high=sum(1 for item in incidents if is_pending(item) and item.risk_level == "high"),
            high=sum(1 for item in incidents if item.risk_level == "high"),
            emotion_escalation=types.get("emotion_escalation", 0),
            adverse_reaction=types.get("adverse_reaction", 0),
        ),
        levels={key: levels.get(key, 0) for key in ("high", "medium", "low")} | {
            key: value for key, value in levels.items() if key not in {"high", "medium", "low"}},
        types=dict(types), hourly=hourly, high_risk_markers=markers,
        customer_messages=counted, negative_share=round(negative / counted, 4) if counted else 0.0,
        emotion_source="rule",
        range_conversation_ids=sorted(active) if ranged else None,
    )


def product_clues(session: Session, date_from: date | None = None,
                  date_to: date | None = None) -> list[ProductClueView]:
    from app.domain.consumer_service.models import (
        AdverseReactionRow,
        ReturnRefundRow,
        ServiceOrderRow,
        WorkOrderRow,
    )
    from app.domain.consumer_service.workspace import active_batch

    batch = active_batch(session)
    if not batch:
        return []
    products = {row.order_id: row.product_name for row in session.scalars(
        select(ServiceOrderRow).where(ServiceOrderRow.batch_id == batch)) if row.product_name}
    details: dict[str, dict] = {}
    for model in (AdverseReactionRow, ReturnRefundRow):
        for row in session.scalars(select(model)):
            details[row.work_order_record_id] = {"model": model.__name__, **json.loads(row.fields_json),
                                                 "abnormal": getattr(row, "abnormal", None)}
    clues: dict[str, dict] = defaultdict(lambda: {"adverse": 0, "medical": 0, "batches": set(),
                                                    "tickets": 0, "abnormal": 0, "ids": [], "cases": []})
    for work in session.scalars(select(WorkOrderRow).where(WorkOrderRow.batch_id == batch)):
        if not _in_range(_cst(work.created_at, imported=True).date().isoformat(), date_from, date_to):
            continue
        detail = details.get(work.record_id, {})
        name = detail.get("product_name") or products.get(work.order_id or "")
        if not name:
            continue
        clue = clues[name]
        clue["tickets"] += 1
        clue["ids"].append(work.work_order_id)
        batch_no = None
        if work.work_order_type == "adverse_reaction":
            raw_batch = str(detail.get("product_batch_no") or "").strip()
            batch_no = "未记录" if raw_batch in UNRECORDED_BATCH else raw_batch
        clue["cases"].append(ProductClueCase(
            work_order_id=work.work_order_id, work_order_type=work.work_order_type, order_id=work.order_id,
            conversation_id=work.conversation_id, buyer_alias=work.buyer_alias, batch=batch_no,
            created_at=_cst(work.created_at, imported=True).isoformat(),
        ))
        if work.work_order_type == "adverse_reaction":
            clue["adverse"] += 1
            clue["medical"] += 1 if str(detail.get("sought_medical_care", "")).strip() == "是" else 0
            batch_no = str(detail.get("product_batch_no") or "").strip()
            clue["batches"].add("未记录" if batch_no in UNRECORDED_BATCH else batch_no)
        if work.work_order_type == "return_refund" and str(detail.get("abnormal", "")).strip() == "是":
            clue["abnormal"] += 1
    result = []
    for name, clue in clues.items():
        if clue["adverse"] < 2 and clue["tickets"] < 5:
            continue
        other = clue["tickets"] - clue["adverse"]
        result.append(ProductClueView(
            product_name=name, adverse_reactions=clue["adverse"], medical_visits=clue["medical"],
            batches=sorted(clue["batches"]), related_tickets=clue["tickets"], other_tickets=other,
            abnormal_returns=clue["abnormal"],
            score=clue["adverse"] * 3 + clue["medical"] * 5 + other,
            work_order_ids=sorted(clue["ids"]),
            cases=sorted(clue["cases"], key=lambda case: (case.batch is None, case.batch or "", case.created_at)),
        ))
    return sorted(result, key=lambda item: (-item.score, item.product_name))
