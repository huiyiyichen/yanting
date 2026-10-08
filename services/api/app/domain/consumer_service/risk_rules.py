"""One deterministic rule set for import, messages, AI assistance and scheduled scans."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.case_state.models import AuditEventRow, CaseRow, ConversationRow, MessageRow
from app.domain.consumer_service.emotion import has_complaint_signal, score_message
from app.domain.consumer_service.mapping import DATASET_ID
from app.domain.consumer_service.models import (
    DatasetRow,
    ServiceConversationRow,
    ServiceMessageRow,
    ServiceOrderRow,
    ServiceRiskAlertRow,
    ServiceTicketDetailRow,
    ServiceTicketRow,
    WorkOrderRow,
)
from app.domain.enums import ServiceRiskLevel as Level
from app.domain.enums import ServiceRiskType as Kind
from app.repositories.consumer_service import _detail
from app.schemas.service_desk import RiskEvidenceView

RULE_VERSION = "loreal-risk-v2.7"
RANK = {Level.UNKNOWN: 0, Level.LOW: 1, Level.MEDIUM: 2, Level.HIGH: 3}
PURSUIT = re.compile(r"还没|到底|进度|催|等了|没解决|没收到|又来|再次")
RELIEF = re.compile(r"已经解决|已解决|解决了|收到[了啦]|不用.{0,3}投诉|不再.{0,3}投诉|谢谢.{0,6}(处理|解决)")
CALM_FOLLOW_UP = re.compile(
    r"^(?:嗯[，, ]*)?(?:这|那)?(?:就)?(?:还差不多|好多了|可以了|行了|没问题了|"
    r"收到啦?|明白了|了解了)(?:[。！!～~]*)$"
)
REACTION = re.compile(r"红肿|刺痛|刺痒|过敏|不适|就医|医院|呼吸困难|脸肿")
ACKNOWLEDGEMENT = re.compile(
    r"^(?:好的?[，, ]*)?(?:谢谢[您啦]?|多谢|好的?|收到|谢谢帮忙)[，,。！!～~ ]*$"
)


def utc(value: datetime | str | None, *, source: bool = False) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value - timedelta(hours=8) if source else value


@dataclass(frozen=True)
class RuleMessage:
    ref: str
    conversation_id: str
    buyer: str
    body: str
    at: datetime
    order_id: str | None = None
    shop: str = ""
    sender_role: str = "customer"
    is_source: bool = True
    service_closed_at: datetime | None = None
    has_attachments: bool = False

    def evidence(self) -> RiskEvidenceView:
        return RiskEvidenceView(
            ref=self.ref, kind="message", label=self.conversation_id, body=self.body,
            conversation_id=self.conversation_id,
            occurred_at=self.at.replace(tzinfo=UTC).isoformat(),
        )


@dataclass(frozen=True)
class RuleTicket:
    ticket_id: str
    ref: str
    conversation_id: str
    buyer: str
    kind: str
    order_id: str | None
    status: str
    created_at: datetime
    detail: dict[str, Any] = field(default_factory=dict)
    completed_at: datetime | None = None
    due_at: datetime | None = None
    local_status: str | None = None
    local_revision: int = 0
    is_source: bool = True
    due_set_at: datetime | None = None

    def evidence(self) -> RiskEvidenceView:
        fields = [
            str(self.detail[key]) for key in (
                "paymentType", "transferStatus", "symptomDescription", "soughtMedicalCare",
                "abnormal", "issueType", "solution",
            ) if self.detail.get(key)
        ]
        return RiskEvidenceView(
            ref=self.ref, kind="work_order" if self.is_source else "followup", label=self.ticket_id,
            conversation_id=self.conversation_id,
            body="；".join([
                f"{'源' if self.is_source else '本地事项'}状态：{self.status}",
                *([f"本地跟进状态：{self.local_status}"] if self.local_status else []), *fields,
            ]),
            occurred_at=self.created_at.replace(tzinfo=UTC).isoformat(),
        )


@dataclass
class RiskSignal:
    conversation_id: str
    buyer: str
    kind: Kind
    level: Level
    reason: str
    at: datetime
    evidence: list[RiskEvidenceView]
    order_ids: list[str] = field(default_factory=list)
    ticket_ids: list[str] = field(default_factory=list)
    active: bool = True
    conditions: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        payload = (self.kind.value, self.order_ids, self.ticket_ids,
                   sorted((e.ref, e.body, e.occurred_at or "") for e in self.evidence),
                   self.at.isoformat())
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def is_refund(ticket: RuleTicket) -> bool:
    payment = str(ticket.detail.get("paymentType", ""))
    state = str(ticket.detail.get("transferStatus", ""))
    return (ticket.kind == "offline_payment" and "退款" in payment
            and not any(v in payment for v in ("补差", "补偿", "赔付"))
            and not any(v in state for v in ("撤销", "拒绝", "取消")))


def waiting_signals(messages: list[RuleMessage], *, now: datetime, wait_seconds: int):
    if wait_seconds <= 0:
        return []
    local_history: dict[str, list[RuleMessage]] = defaultdict(list)
    for message in sorted(messages, key=lambda item: (item.at, item.ref)):
        if not message.is_source and message.at <= now:
            local_history[message.conversation_id].append(message)
    result: list[RiskSignal] = []
    for cid, history in local_history.items():
        customers = [message for message in history if message.sender_role == "customer"]
        if not customers:
            continue
        latest = customers[-1]
        text = latest.body.strip()
        if score_message(text) == 0 and (
            RELIEF.search(text) or CALM_FOLLOW_UP.fullmatch(text) or ACKNOWLEDGEMENT.fullmatch(text)
        ):
            continue
        replies = [message.at for message in history
                   if message.sender_role in {"operator", "assistant"}
                   and (message.body.strip() or message.has_attachments)]
        boundary = max([*replies, *[message.service_closed_at for message in history
                                  if message.service_closed_at]], default=None)
        pending = [message for message in customers if boundary is None or message.at > boundary]
        if not pending:
            continue
        started = pending[0]
        deadline = started.at + timedelta(seconds=wait_seconds)
        if now < deadline:
            continue
        evidence = list({message.ref: message.evidence() for message in [started, latest]}.values())
        result.append(RiskSignal(
            cid, latest.buyer, Kind.RESPONSE_WAIT, Level.MEDIUM,
            f"本次消费者等待已超过{wait_seconds}秒，尚无可见服务回复",
            deadline, evidence, [latest.order_id] if latest.order_id else [],
            conditions={
                "basis": "local_response_wait", "demoRule": True,
                "waitThresholdSeconds": wait_seconds,
                "waitingSince": started.at.replace(tzinfo=UTC).isoformat(),
                "deadlineAt": deadline.replace(tzinfo=UTC).isoformat(),
            },
        ))
    return result


def compute_signals(
    messages: list[RuleMessage], tickets: list[RuleTicket], *,
    now: datetime, source_clock: datetime | None,
    repeat_hours: int = 72, overdue_hours: int = 48,
    response_wait_seconds: int = 120, followup_warning_minutes: int = 30,
) -> list[RiskSignal]:
    by_conversation: dict[str, list[RuleMessage]] = defaultdict(list)
    for message in sorted(messages, key=lambda m: (m.at, m.ref)):
        if message.sender_role == "customer":
            by_conversation[message.conversation_id].append(message)
    by_order: dict[str, list[RuleTicket]] = defaultdict(list)
    for ticket in tickets:
        if ticket.order_id:
            by_order[ticket.order_id].append(ticket)
    signals = waiting_signals(messages, now=now, wait_seconds=response_wait_seconds)
    first_contacts = [rows[0] for rows in by_conversation.values()]
    for cid, history in by_conversation.items():
        latest = history[-1]
        calming = score_message(latest.body) == 0 and (
            bool(RELIEF.search(latest.body)) or bool(CALM_FOLLOW_UP.search(latest.body.strip()))
        )
        calm_conditions = (
            {"clearReason": "consumer_calm_follow_up", "clearEvidence": latest.ref}
            if calming else {}
        )
        baseline: RuleMessage | None = None
        escalation: tuple[RuleMessage, RuleMessage, Level, RuleMessage | None] | None = None
        highest = Level.LOW
        strongest: RuleMessage | None = None
        complaint: RuleMessage | None = None
        for message in history:
            score = score_message(message.body)
            if score < 2 and message.body.strip():
                baseline = message
                if RELIEF.search(message.body):
                    highest, strongest = Level.MEDIUM, None
            elif score == 2 and baseline:
                if has_complaint_signal(message.body):
                    highest, strongest = Level.HIGH, message
                elif PURSUIT.search(message.body):
                    highest = max(highest, Level.MEDIUM, key=lambda value: RANK[value])
                escalation = (baseline, message, highest, strongest)
            if has_complaint_signal(message.body):
                complaint = message
        if escalation:
            start, trigger, level, strongest = escalation
            orders = [trigger.order_id] if trigger.order_id else []
            related = [w.ticket_id for w in tickets if w.order_id in orders]
            signals.append(RiskSignal(
                cid, latest.buyer, Kind.EMOTION_ESCALATION,
                level,
                f"消费者从平稳或不满升级为愤怒：{trigger.body[:100]}",
                trigger.at, list({m.ref: m.evidence() for m in
                                  [start, trigger, *([strongest] if strongest else [])]}.values()) +
                ([latest.evidence()] if calming and latest.at > trigger.at else []), orders, related,
                active=not (calming and latest.at > trigger.at),
                conditions=calm_conditions if calming and latest.at > trigger.at else {},
            ))
        if complaint:
            signals.append(RiskSignal(
                cid, latest.buyer, Kind.COMPLAINT_RISK, Level.HIGH,
                f"消费者表达投诉诉求：{complaint.body[:100]}", complaint.at,
                [complaint.evidence()] +
                ([latest.evidence()] if calming and latest.at > complaint.at else []),
                [complaint.order_id] if complaint.order_id else [],
                active=not (calming and latest.at > complaint.at),
                conditions=calm_conditions if calming and latest.at > complaint.at else {},
            ))
        current_first = history[0]
        contacts = [m for m in first_contacts
                    if m.buyer and m.buyer == latest.buyer and m.shop == current_first.shop
                    and timedelta(0) <= current_first.at - m.at <= timedelta(hours=repeat_hours)]
        if len(contacts) > 1:
            signals.append(RiskSignal(
                cid, latest.buyer, Kind.REPEATED_CONTACT, Level.MEDIUM,
                f"{repeat_hours}小时内存在{len(contacts)}次进线，需核对是否为同一诉求",
                current_first.at, [m.evidence() for m in contacts],
                conditions={
                    "windowHours": repeat_hours, "contactCount": len(contacts),
                    "identityBasis": "buyer_alias_and_shop",
                    **(calm_conditions if calming else {}),
                },
                active=not calming,
            ))
        reaction_messages = [m for m in history if REACTION.search(m.body)]
        if reaction_messages:
            trigger = reaction_messages[-1]
            severe = any(t in trigger.body for t in ("就医", "医院", "呼吸困难", "脸肿"))
            # This flags a customer's report, never a medical diagnosis.
            if severe and trigger is latest:
                signals.append(RiskSignal(
                    cid, latest.buyer, Kind.ADVERSE_REACTION, Level.HIGH,
                    "消费者自述使用后不适或就医，需要人工优先核实",
                    trigger.at, [trigger.evidence()],
                    [trigger.order_id] if trigger.order_id else [],
                ))

    for ticket in tickets:
        related_messages = [
            m for m in messages if m.sender_role == "customer" and (
                m.conversation_id == ticket.conversation_id
                or (ticket.order_id and m.order_id == ticket.order_id)
            )
        ]
        pursuing = [m for m in related_messages if m.at >= ticket.created_at and PURSUIT.search(m.body)]
        orders = [ticket.order_id] if ticket.order_id else []
        if ticket.kind == "adverse_reaction":
            signals.append(RiskSignal(
                ticket.conversation_id, ticket.buyer, Kind.ADVERSE_REACTION, Level.HIGH,
                "存在不良反应服务记录，需要人工复核症状自述和处理结果",
                ticket.created_at, [ticket.evidence()], orders, [ticket.ticket_id],
                active=(ticket.local_status or ticket.status) not in {"completed", "resolved"},
            ))
        if ticket.kind == "return_refund" and ticket.detail.get("abnormal") == "是":
            signals.append(RiskSignal(
                ticket.conversation_id, ticket.buyer, Kind.ABNORMAL_RETURN, Level.MEDIUM,
                "退货源记录标记异常，需要核对签收及处理依据",
                ticket.created_at, [ticket.evidence()], orders, [ticket.ticket_id],
                active=(ticket.local_status or ticket.status) not in {"completed", "resolved"},
            ))
        if ticket.due_at and ticket.due_at <= now and ticket.local_status != "resolved":
            due_evidence = RiskEvidenceView(
                ref=f"ticket:{ticket.ticket_id}:due:{ticket.due_at.isoformat()}",
                kind="followup", label=ticket.ticket_id,
                body=f"约定跟进时间：{ticket.due_at.replace(tzinfo=UTC).isoformat()}，当前尚未完成跟进",
                occurred_at=ticket.due_at.replace(tzinfo=UTC).isoformat(),
            )
            signals.append(RiskSignal(
                ticket.conversation_id, ticket.buyer, Kind.WORK_ORDER_OVERDUE, Level.HIGH,
                "本地工单超过约定跟进时间，待负责人处理",
                ticket.due_at, [ticket.evidence(), due_evidence], orders, [ticket.ticket_id],
                conditions={"basis": "explicit_followup_deadline"},
            ))
        elif (followup_warning_minutes > 0 and ticket.due_at and ticket.local_status
              and ticket.local_status != "resolved"
              and now < ticket.due_at <= now + timedelta(minutes=followup_warning_minutes)):
            due_at = ticket.due_at.replace(tzinfo=UTC).isoformat()
            warning_at = max(
                ticket.created_at, ticket.due_at - timedelta(minutes=followup_warning_minutes),
                *([ticket.due_set_at] if ticket.due_set_at else []),
            )
            due_evidence = RiskEvidenceView(
                ref=f"ticket:{ticket.ticket_id}:upcoming:{due_at}",
                kind="followup", label=ticket.ticket_id,
                body=f"约定跟进时间：{due_at}；尚未完成跟进，提前{followup_warning_minutes}分钟提醒",
                occurred_at=warning_at.replace(tzinfo=UTC).isoformat(),
            )
            signals.append(RiskSignal(
                ticket.conversation_id, ticket.buyer, Kind.FOLLOWUP_DUE_SOON, Level.MEDIUM,
                "约定跟进即将到期，当前尚未完成，需提前核对进展",
                warning_at, [ticket.evidence(), due_evidence], orders, [ticket.ticket_id],
                conditions={
                    "basis": "followup_due_soon", "demoRule": True,
                    "warningMinutes": followup_warning_minutes,
                    "deadlines": [{"ticketId": ticket.ticket_id, "dueAt": due_at}],
                },
            ))
        elif (ticket.is_source and source_clock and pursuing
              and ticket.status not in {"completed", "resolved"}
              and source_clock - ticket.created_at >= timedelta(hours=overdue_hours)):
            trigger = max(pursuing, key=lambda m: m.at)
            signals.append(RiskSignal(
                trigger.conversation_id, trigger.buyer, Kind.WORK_ORDER_OVERDUE, Level.MEDIUM,
                f"源工单在数据快照中超过{overdue_hours}小时未完结，消费者继续追问",
                max(ticket.created_at + timedelta(hours=overdue_hours), trigger.at),
                [ticket.evidence(), trigger.evidence()], orders, [ticket.ticket_id],
                active=ticket.local_status != "resolved",
                conditions={"windowHours": overdue_hours, "basis": "source_snapshot",
                            "referenceTime": source_clock.replace(tzinfo=UTC).isoformat()},
            ))
        if ticket.completed_at:
            after = [m for m in pursuing if m.at > ticket.completed_at]
            if after:
                trigger = max(after, key=lambda m: m.at)
                latest_feedback = max(related_messages, key=lambda m: m.at)
                resolved_feedback = (
                    latest_feedback.at > trigger.at
                    and score_message(latest_feedback.body) == 0
                    and bool(RELIEF.search(latest_feedback.body))
                )
                signals.append(RiskSignal(
                    trigger.conversation_id, trigger.buyer, Kind.DATA_CONFLICT, Level.MEDIUM,
                    "记录完成后消费者仍在追问，需核实是否为同一问题",
                    trigger.at, [ticket.evidence(), trigger.evidence()] +
                    ([latest_feedback.evidence()] if resolved_feedback else []),
                    orders, [ticket.ticket_id], active=not resolved_feedback,
                    conditions={"clearReason": "consumer_resolved_follow_up",
                                "clearEvidence": latest_feedback.ref} if resolved_feedback else {},
                ))
    for order_id, order_tickets in by_order.items():
        refunds = [w for w in order_tickets if is_refund(w)]
        returns = [w for w in order_tickets if w.kind == "return_refund"
                   and w.status not in {"cancelled", "rejected"}]
        # Several records with the same refund ID are one request, not multiple refunds.
        returns = list({str(w.detail.get("refundId") or w.ticket_id): w for w in returns}.values())
        duplicates = refunds if len(refunds) > 1 else returns if len(returns) > 1 else []
        if duplicates:
            trigger = max(duplicates, key=lambda w: (w.created_at, w.ticket_id))
            signals.append(RiskSignal(
                trigger.conversation_id, trigger.buyer, Kind.REPEATED_REFUND, Level.HIGH,
                f"订单{order_id}存在{len(duplicates)}笔独立退款或退货记录，需人工核对",
                trigger.created_at, [w.evidence() for w in duplicates], [order_id],
                [w.ticket_id for w in duplicates],
                active=any((w.local_status or w.status) not in {"completed", "resolved"}
                           for w in duplicates),
                conditions={"independentRequests": len(duplicates)},
            ))
    # One type per conversation, retaining every actual order/ticket link rather than choosing the first.
    grouped: dict[tuple[str, Kind], RiskSignal] = {}
    for signal in signals:
        key = (signal.conversation_id, signal.kind)
        if key not in grouped:
            grouped[key] = signal
            continue
        old = grouped[key]
        old.reason = "；".join(dict.fromkeys([old.reason, signal.reason]))
        old.at, old.active = max(old.at, signal.at), old.active or signal.active
        old.level = max(old.level, signal.level, key=RANK.get)
        old.order_ids = sorted(set(old.order_ids + signal.order_ids))
        old.ticket_ids = sorted(set(old.ticket_ids + signal.ticket_ids))
        old.evidence = list({e.ref: e for e in old.evidence + signal.evidence}.values())
        deadlines = [*old.conditions.get("deadlines", []), *signal.conditions.get("deadlines", [])]
        old.conditions.update(signal.conditions)
        if deadlines:
            old.conditions["deadlines"] = list({
                (item["ticketId"], item["dueAt"]): item for item in deadlines
            }.values())
    return list(grouped.values())


def load_rule_inputs(session: Session, batch_id: str):
    conversations = {c.conversation_id: c for c in session.scalars(
        select(ServiceConversationRow).where(ServiceConversationRow.batch_id == batch_id)
    )}
    orders = {o.order_id: o for o in session.scalars(
        select(ServiceOrderRow).where(ServiceOrderRow.batch_id == batch_id)
    )}
    order_by_conversation: dict[str, set[str]] = defaultdict(set)
    for order in orders.values():
        order_by_conversation[order.conversation_id].add(order.order_id)
    source_messages = list(session.scalars(
        select(ServiceMessageRow).where(
            ServiceMessageRow.batch_id == batch_id, ServiceMessageRow.sender_role == "customer",
        ).order_by(ServiceMessageRow.sent_at, ServiceMessageRow.sequence)
    ))
    local_conversations = {r.conversation_id: r for r in session.scalars(select(ConversationRow))}
    closed_cases = {
        row.conversation_id: utc(row.closed_at) for row in session.scalars(select(CaseRow).where(
            CaseRow.case_status == "closed", CaseRow.closed_at.is_not(None),
        ))
    }
    local_messages = list(session.scalars(select(MessageRow).order_by(
        MessageRow.created_at, MessageRow.applies_to_message_revision,
    )))
    for message in local_messages:
        if message.sender_role != "customer":
            continue
        for token in re.findall(r"(?<![A-Za-z0-9])[A-Za-z]*\d{6,}(?![A-Za-z0-9])", message.body or ""):
            if token in orders:
                order_by_conversation[message.conversation_id].add(token)
    messages = []
    for row in source_messages:
        possible = order_by_conversation[row.conversation_id]
        order_id = row.order_id or (next(iter(possible)) if len(possible) == 1 else None)
        messages.append(RuleMessage(row.source_record_id, row.conversation_id, row.buyer_alias,
                                    row.body or "", utc(row.sent_at, source=True), order_id, row.shop or ""))
    for row in local_messages:
        if row.conversation_id not in local_conversations:
            continue
        local = local_conversations[row.conversation_id]
        explicit = [o for o in orders if row.sender_role == "customer"
                    and re.search(rf"(?<!\d){re.escape(o)}(?!\d)", row.body or "")]
        possible = set(explicit) or order_by_conversation[row.conversation_id]
        order_id = next(iter(possible)) if len(possible) == 1 else None
        buyer = conversations[row.conversation_id].buyer_alias if row.conversation_id in conversations else local.customer_id
        shop = orders[order_id].shop if order_id else ""
        messages.append(RuleMessage(row.message_id, row.conversation_id, buyer or local.customer_id,
                                    row.body or "", utc(row.created_at), order_id, shop or "",
                                    sender_role=row.sender_role, is_source=False,
                                    service_closed_at=closed_cases.get(row.conversation_id),
                                    has_attachments=bool(json.loads(row.attachments_json))))
    overlays = {r.ticket_id: r for r in session.scalars(select(ServiceTicketRow))}
    deadline_updates: dict[str, tuple[str | None, datetime]] = {}
    for event in session.scalars(select(AuditEventRow).where(
        AuditEventRow.event_type == "ticket_deadline_changed",
    ).order_by(AuditEventRow.created_at, AuditEventRow.audit_event_id)):
        detail = json.loads(event.detail_json)
        if detail.get("ticketId"):
            deadline_updates[detail["ticketId"]] = (detail.get("dueAt"), utc(event.created_at))

    def due_set_at(ticket: ServiceTicketRow | None) -> datetime | None:
        if ticket is None or ticket.due_at is None:
            return None
        recorded = deadline_updates.get(ticket.ticket_id)
        due_at = utc(ticket.due_at).replace(tzinfo=UTC).isoformat()
        return recorded[1] if recorded and recorded[0] == due_at else None

    local_details = {r.ticket_id: json.loads(r.payload_json)
                     for r in session.scalars(select(ServiceTicketDetailRow))}
    tickets = []
    source_ids = set()
    for row in session.scalars(select(WorkOrderRow).where(WorkOrderRow.batch_id == batch_id)):
        source_ids.add(row.work_order_id)
        local = overlays.get(row.work_order_id)
        tickets.append(RuleTicket(
            row.work_order_id, row.source_record_id, row.conversation_id, row.buyer_alias,
            row.work_order_type, row.order_id, row.normalized_status, utc(row.created_at, source=True),
            _detail(session, row),
            utc(local.updated_at) if local and local.status == "resolved" else utc(row.completed_at, source=True),
            utc(local.due_at) if local else None, local.status if local else None,
            local.revision if local else 0,
            due_set_at=due_set_at(local),
        ))
    for row in overlays.values():
        if row.ticket_id in source_ids or row.source_record_id:
            continue
        detail = dict(local_details.get(row.ticket_id, {}))
        if detail.get("paymentType"):
            detail["paymentType"] = {
                "refund": "退款申请", "price_adjustment": "补差申请", "compensation": "补偿申请",
            }[detail["paymentType"]]
        tickets.append(RuleTicket(
            row.ticket_id, f"ticket:{row.ticket_id}", row.conversation_id, row.buyer_alias,
            row.work_order_type, row.order_id, row.status, utc(row.created_at),
            detail=detail,
            completed_at=utc(row.updated_at) if row.status == "resolved" else None,
            due_at=utc(row.due_at), local_status=row.status, local_revision=row.revision,
            is_source=False,
            due_set_at=due_set_at(row),
        ))
    source_clock = utc(session.scalar(select(func.max(ServiceMessageRow.sent_at)).where(
        ServiceMessageRow.batch_id == batch_id,
    )), source=True)
    return messages, tickets, source_clock


def evaluate_risks(
    session: Session, *, batch_id: str | None = None, now: datetime | None = None,
) -> list[ServiceRiskAlertRow]:
    from app.domain.consumer_service.risk import RiskAlertRepository

    dataset = session.get(DatasetRow, DATASET_ID)
    batch_id = batch_id or (dataset.active_batch_id if dataset else None)
    if not batch_id:
        return []
    # Serialize evaluation with message/ticket writes, without changing the published data pointer.
    session.execute(update(DatasetRow).where(DatasetRow.dataset_id == DATASET_ID)
                    .values(active_batch_id=DatasetRow.active_batch_id))
    settings = get_settings()
    messages, tickets, source_clock = load_rule_inputs(session, batch_id)
    signals = compute_signals(
        messages, tickets, now=utc(now) if now else datetime.now(UTC).replace(tzinfo=None),
        source_clock=source_clock, repeat_hours=settings.risk_repeat_contact_hours,
        overdue_hours=settings.risk_source_ticket_hours,
        response_wait_seconds=settings.risk_response_wait_seconds,
        followup_warning_minutes=settings.risk_followup_warning_minutes,
    )
    from app.domain.consumer_service.service_breakpoints import assessment_signals

    signals.extend(assessment_signals(session, batch_id))
    repository = RiskAlertRepository(session)
    rows = [repository.apply_signal(batch_id, signal) for signal in signals]
    repository.mark_quiet(batch_id, {row.alert_id for row in rows})
    session.flush()
    return rows


async def run_risk_monitor(runtime: Any) -> None:
    import asyncio

    from app.logging_setup import get_logger

    def tick():
        with runtime.new_session() as session:
            evaluate_risks(session)
            session.commit()

    while True:
        try:
            await asyncio.to_thread(tick)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            get_logger(__name__).warning("Risk monitor: %s", type(exc).__name__)
        await asyncio.sleep(runtime.settings.risk_monitor_interval_seconds)
