"""Risk events aggregate evidence; ticket progress never closes a risk automatically."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.case_state.models import MessageRow
from app.domain.consumer_service.emotion import emotion_trend, has_complaint_signal, score_message
from app.domain.consumer_service.models import (
    DatasetRow,
    RiskEpisodeRow,
    RiskLifecycleRow,
    ServiceTicketRow,
)
from app.domain.consumer_service.operators import DEFAULT_OPERATOR
from app.domain.consumer_service.risk import (
    RiskAlertRepository,
    current_signal_attention,
    risk_alert_view,
    signal_attention,
)
from app.domain.consumer_service.service_breakpoints import moment
from app.domain.consumer_service.tickets import events_for, list_tickets, record_event
from app.domain.consumer_service.workspace import (
    active_batch,
    conversation_messages,
    risk_service_states,
)
from app.domain.enums import ServiceRiskStatus
from app.errors import ConflictError, NotFoundError, ValidationRejected
from app.repositories.consumer_service import ConsumerServiceRepository
from app.schemas.service_desk import (
    RiskEmotionView,
    RiskEpisodeView,
    RiskEvidenceView,
    RiskIncidentDetailView,
    RiskIncidentView,
    RiskScanView,
    RiskServicePointView,
)

LEVEL_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}
TRIAGE_LABELS = {
    "urgent": "立即处置",
    "priority": "优先处置",
    "review": "待复核",
    "normal": "常规",
}


def _triage_priority(
    signals: list, *, status: str, open_ticket_count: int, needs_review: bool,
    recurrence_count: int, signal_active: bool, service_state: str = "live",
    historical_sensitivity: int = 0,
) -> tuple[int, str, list[str]]:
    """Rank operator attention without changing risk status or ticket state."""
    if status in {"resolved", "ignored"}:
        return 0, "normal", ["已关闭"]
    if service_state == "historical":
        return 0, "normal", ["历史服务记录"]
    current_signals = [
        signal for signal in signals if (getattr(signal, "current_attention", None) or signal_attention(
            signal.risk_status.value, signal_active=signal.signal_active,
            analysis_stale=bool(signal.conditions.get("analysisStale")),
        )) == "active"
    ]
    if not current_signals:
        return 10, "review", ["待人工复核", "暂无当前有效触发"]
    score = {
        "unknown": 5, "low": 15, "medium": 30, "high": 45,
    }[max(
        (signal.risk_level.value for signal in current_signals),
        key=lambda value: LEVEL_RANK[value],
        default="unknown",
    )]
    reasons: list[str] = []
    if score >= 45:
        reasons.append("高风险")
    risk_types = {signal.risk_type.value for signal in current_signals}
    for risk_type, points, label in (
        ("adverse_reaction", 20, "不良反应"),
        ("repeated_refund", 18, "重复退款/退货"),
        ("data_conflict", 14, "数据冲突"),
        ("emotion_escalation", 12, "情绪升级"),
        ("service_breakpoint", 12, "服务断点"),
        ("repeated_contact", 10, "重复进线"),
        ("abnormal_return", 10, "异常退货"),
        ("work_order_overdue", 10, "工单逾期"),
        ("response_wait", 8, "尚未回复"),
        ("followup_due_soon", 10, "跟进临近截止"),
    ):
        if risk_type in risk_types:
            score += points
            reasons.append(label)
    if recurrence_count:
        score += min(recurrence_count * 8, 16)
        reasons.append(f"复发{recurrence_count}次")
    if historical_sensitivity:
        score += min(historical_sensitivity * 4, 12)
        reasons.append(f"历史风险敏感度{historical_sensitivity}/3")
    if needs_review:
        score += 10
        reasons.append("待人工复核")
    if signal_active and open_ticket_count == 0:
        score += 8
        reasons.append("尚无进行中工单")
    if status == "pending":
        score += 5
        reasons.append("尚未介入")
    if not signal_active:
        reasons.append("触发条件已消退")
    score = min(score, 100)
    if needs_review and not signal_active:
        label = "review"
    elif score >= 70:
        label = "urgent"
    elif score >= 45:
        label = "priority"
    else:
        label = "normal"
    return score, label, reasons


def _messages(session: Session, conversation_id: str):
    try:
        return conversation_messages(session, conversation_id)
    except NotFoundError:
        # Risk evidence/history is retained even after a local demo conversation is removed.
        return []


def _emotion_history(session: Session, conversation_id: str) -> list[RiskEmotionView]:
    history = []
    for message in _messages(session, conversation_id):
        at = moment(message.created_at)
        if message.sender_role.value != "customer" or not message.body.strip() or at is None:
            continue
        factors = []
        if has_complaint_signal(message.body):
            factors.append("投诉表达")
        if any(term in message.body for term in ("等了", "多久", "还没", "怎么还", "到底", "快点", "赶紧", "别拖")):
            factors.append("等待追问")
        if any(term in message.body for term in ("漏发", "少发", "破损", "假货", "不对", "不舒服", "发红", "刺痛", "痒")):
            factors.append("商品或服务问题")
        history.append(RiskEmotionView(
            message_id=message.message_id, conversation_id=conversation_id,
            occurred_at=at.isoformat(), body=message.body,
            emotion={0: "calm", 1: "dissatisfied", 2: "angry"}[score_message(message.body)],
            trigger_factors=factors,
        ))
    return sorted(history, key=lambda item: item.occurred_at)


def _service_points(session: Session, conversation_ids: list[str]) -> list[RiskServicePointView]:
    points = []
    for conversation_id in conversation_ids:
        for message in _messages(session, conversation_id):
            at = moment(message.created_at)
            if message.sender_role.value not in {"operator", "assistant"} or not message.body.strip() or at is None:
                continue
            points.append(RiskServicePointView(
                message_id=message.message_id,
                conversation_id=conversation_id,
                occurred_at=at.isoformat(),
                body=message.body,
                sender_role=message.sender_role.value,
            ))
    return sorted(points, key=lambda item: item.occurred_at)


def _emotion_comparisons(
    session: Session, conversation_ids: list[str], primary_conversation_id: str,
) -> list[dict]:
    return [
        {"conversation_id": conversation_id, "points": _emotion_history(session, conversation_id)}
        for conversation_id in conversation_ids
        if conversation_id != primary_conversation_id
        and _emotion_history(session, conversation_id)
    ]


def list_incidents(
    session: Session, *, conversation_id: str | None = None,
) -> list[RiskIncidentView]:
    from app.domain.consumer_service.risk_judgments import latest_judgments

    order_scope = (
        {order.order_id for order in ConsumerServiceRepository(session).context(conversation_id).orders}
        if conversation_id is not None else set()
    )
    batch = active_batch(session)
    if batch is None:
        return []
    alert_rows = RiskAlertRepository(session).list(batch_id=batch)
    groups: dict[str, list] = defaultdict(list)
    for row in alert_rows:
        # Only exact order links merge across conversations; an alias is not an identity.
        key = f"order:{row.order_id}" if row.order_id else f"conversation:{row.conversation_id}"
        groups[key].append(row)
    tickets = list_tickets(session)
    service_states = risk_service_states(session)
    local_message_ids = set(session.scalars(select(MessageRow.message_id)))
    local_ticket_ids = set(session.scalars(select(ServiceTicketRow.ticket_id)))
    judgments = latest_judgments(session, [row.alert_id for rows in groups.values() for row in rows])
    sensitivity_by_buyer: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for row in alert_rows:
        if row.risk_type not in {"emotion_escalation", "complaint_risk"}:
            continue
        view = risk_alert_view(row, session)
        attention = current_signal_attention(
            view,
            local_message_ids=local_message_ids,
            local_ticket_ids=local_ticket_ids,
            judgment=judgments.get(row.alert_id),
        )
        if attention in {"historical", "review"} or row.risk_status in {"resolved", "ignored"}:
            sensitivity_by_buyer[row.buyer_alias].add((row.conversation_id, row.risk_type))
    result = []
    for key, rows in groups.items():
        conversations = sorted({row.conversation_id for row in rows})
        signals = [risk_alert_view(row, session) for row in rows]
        for signal in signals:
            signal.current_attention = current_signal_attention(
                signal, local_message_ids=local_message_ids, local_ticket_ids=local_ticket_ids,
                judgment=judgments.get(signal.alert_id),
            )
        orders = sorted({order_id for signal in signals for order_id in signal.order_ids})
        if (conversation_id is not None and conversation_id not in conversations
                and not order_scope.intersection(orders)):
            continue
        related = [t for t in tickets if t.conversation_id in conversations or t.order_id in orders]
        latest = [
            m for cid in conversations for m in _messages(session, cid)
            if m.sender_role.value == "customer"
        ]
        latest.sort(key=lambda m: moment(m.created_at) or datetime.min.replace(tzinfo=UTC))
        open_count = sum(t.status != "resolved" for t in related)
        live_signals = [s for s in signals if s.current_attention in {"active", "review"}]
        current_signals = [s for s in live_signals if s.current_attention == "active"]
        actionable_conversations = {
            s.conversation_id for s in current_signals or live_signals
        }
        live_conversations = {
            cid for cid in actionable_conversations
            if service_states.get(cid, ("historical", None))[0] == "live"
        }
        primary_message = next(
            (message for message in reversed(latest)
             if message.conversation_id in (live_conversations or actionable_conversations)),
            latest[-1] if latest else None,
        )
        primary_conversation_id = (
            primary_message.conversation_id if primary_message else conversations[0]
        )
        current_emotion = {
            0: "calm", 1: "dissatisfied", 2: "angry",
        }.get(score_message(primary_message.body), "unknown") if primary_message and primary_message.body.strip() else "unknown"
        latest_at = moment(primary_message.created_at) if primary_message else None
        trail = _emotion_history(session, primary_conversation_id)
        statuses = {s.risk_status.value for s in current_signals or live_signals or signals}
        status = next((item for item in ("pending", "in_progress", "resolved", "ignored")
                       if item in statuses), "pending")
        level = max(
            (s.risk_level.value for s in current_signals or live_signals or signals),
            key=lambda value: LEVEL_RANK[value],
        )
        recurrence_count = max(s.episode - 1 for s in signals)
        historical_sensitivity = min(3, len(sensitivity_by_buyer.get(rows[0].buyer_alias, set())))
        states = [
            service_states.get(cid, ("historical", None))
            for cid in set(conversations) | {ticket.conversation_id for ticket in related}
        ]
        service_state = (
            "live" if any(state == "live" for state, _ in states)
            else "closed" if any(state == "closed" for state, _ in states)
            else "historical"
        )
        service_closed_at = max(
            (at for state, at in states if state == "closed" and at),
            default=None,
        ) if service_state == "closed" else None
        # Reception closure is not evidence that an independent service obligation ended.
        actionable_signals = current_signals
        signal_active = bool(actionable_signals)
        needs_review = bool(live_signals) and (
            len(current_signals) != len(live_signals)
            or (bool(related) and open_count == 0 and status == "in_progress")
        )
        version = hashlib.sha256(json.dumps({
            "signals": sorted((s.alert_id, s.episode, s.revision, s.risk_status.value) for s in signals),
            "attention": sorted((s.alert_id, s.current_attention) for s in signals),
            "serviceState": service_state, "closedAt": service_closed_at,
            "latestCustomer": (latest[-1].message_id, latest[-1].body) if latest else None,
            "primaryConversation": primary_conversation_id,
            "tickets": sorted((t.ticket_id, t.revision) for t in related),
        }, ensure_ascii=False).encode()).hexdigest()[:20]
        triage_score, triage_label, triage_reasons = _triage_priority(
            signals, status=status, open_ticket_count=open_count, needs_review=needs_review,
            recurrence_count=recurrence_count, signal_active=signal_active,
            service_state=service_state, historical_sensitivity=historical_sensitivity,
        )
        current_actions = [
            signal.recommended_action for signal in actionable_signals
        ]
        historical_signals = any(s.current_attention == "historical" for s in signals)
        attention_state = (
            "active" if current_signals else "review" if live_signals or historical_signals else "closed"
        )
        current_action = (
            "intervene" if actionable_signals
            else "review" if live_signals
            else "record_only" if historical_signals
            else "none"
        )
        result.append(RiskIncidentView(
            incident_id="incident-" + hashlib.sha256(f"{batch}:{key}".encode()).hexdigest()[:16],
            buyer_alias=rows[0].buyer_alias, conversation_ids=conversations, order_ids=orders,
            primary_conversation_id=primary_conversation_id,
            work_order_ids=sorted({t.ticket_id for t in related}),
            risk_level=level, risk_status=status, signals=signals,
            latest_message=primary_message.body if primary_message else "",
            updated_at=max(row.updated_at.replace(tzinfo=UTC) for row in rows).isoformat(),
            recommended_action=(
                "；".join(dict.fromkeys(current_actions)) if current_actions
                else "仅作历史记录，不进入当前处置" if current_action == "record_only"
                else "核对最新反馈与处理结果，确认后关闭" if live_signals
                else "无需继续处置"
            ),
            open_ticket_count=open_count,
            needs_review=needs_review,
            recurrence_count=recurrence_count,
            signal_active=signal_active, version=version,
            judgments=[judgments[row.alert_id] for row in rows if row.alert_id in judgments],
            triage_score=triage_score, triage_label=triage_label,
            triage_reasons=triage_reasons,
            historical_sensitivity=historical_sensitivity,
            attention_state=attention_state,
            current_emotion=current_emotion,
            emotion_trend=(
                emotion_trend(item.body for item in trail[-2:]).value
                if current_emotion != "unknown" else "unknown"
            ),
            service_state=service_state,
            service_closed_at=service_closed_at,
            latest_customer_at=latest_at.isoformat() if latest_at else None,
            current_action=current_action,
        ))
    return sorted(result, key=lambda item: (
        {"none": 0, "record_only": 0, "review": 1, "intervene": 2}[item.current_action],
        item.triage_score, LEVEL_RANK[item.risk_level], item.updated_at,
    ), reverse=True)


def _legacy_contact_context(
    session: Session, signal, contexts: list,
) -> tuple[list[RiskEvidenceView], dict[str, object]]:
    if signal.risk_type.value != "repeated_contact" or signal.rule_version != "legacy":
        return [], {}
    conversation_ids: list[str] = []
    for context in contexts:
        if context.conversation_id != signal.conversation_id:
            continue
        conversation_ids.extend([context.conversation_id, *(context.history_conversation_ids or [])])
    conversation_ids = list(dict.fromkeys(conversation_ids))
    evidence: list[RiskEvidenceView] = []
    for conversation_id in conversation_ids:
        customer_message = next(
            (
                message for message in _messages(session, conversation_id)
                if message.sender_role.value == "customer" and message.body
            ),
            None,
        )
        if customer_message is None:
            continue
        evidence.append(RiskEvidenceView(
            ref=customer_message.message_id,
            kind="history_context",
            label=conversation_id,
            body=customer_message.body,
            occurred_at=customer_message.created_at,
        ))
    if len(evidence) < 2:
        return evidence, {}
    return evidence, {
        "basis": "legacy_context_history",
        "contactCount": len(evidence),
        "conversationIds": [item.label for item in evidence],
    }


def incident_detail(session: Session, incident_id: str) -> RiskIncidentDetailView:
    from app.domain.consumer_service.risk_judgments import judgment_history
    from app.domain.consumer_service.service_breakpoints import read_assessment
    incident = next((item for item in list_incidents(session) if item.incident_id == incident_id), None)
    if incident is None:
        raise NotFoundError("风险事件不存在")
    contexts = []
    for cid in incident.conversation_ids:
        try:
            contexts.append(ConsumerServiceRepository(session).context(cid))
        except NotFoundError:
            continue
    contact_history: dict[str, RiskEvidenceView] = {}
    for signal in incident.signals:
        evidence_views, _ = _legacy_contact_context(session, signal, contexts)
        contact_history.update({item.ref: item for item in evidence_views})
    evidence: dict[str, RiskEvidenceView] = {}
    refs = {ref for signal in incident.signals for ref in signal.evidence_refs}
    for context in contexts:
        for event in context.timeline:
            if event.source_record_id not in refs:
                continue
            body = (event.message.body or "") if event.message else (
                event.work_order.source_status if event.work_order else
                event.order.source_status or "" if event.order else event.event_type
            )
            evidence[event.source_record_id] = RiskEvidenceView(
                ref=event.source_record_id, kind=event.entity_type,
                label=context.conversation_id, body=body, occurred_at=event.occurred_at,
            )
        for message in _messages(session, context.conversation_id):
            if message.message_id in refs:
                evidence[message.message_id] = RiskEvidenceView(
                    ref=message.message_id, kind="message", label=context.conversation_id,
                    body=message.body, occurred_at=message.created_at,
                )
    for ref in refs - evidence.keys():
        evidence[ref] = RiskEvidenceView(ref=ref, kind="source", label="关联记录", body=ref)
    history_ids = {incident_id}
    for signal in incident.signals:
        metadata = session.get(RiskLifecycleRow, signal.alert_id)
        if metadata:
            history_ids.update(json.loads(metadata.incident_ids_json))
            for item in json.loads(metadata.evidence_json):
                view = RiskEvidenceView.model_validate(item)
                evidence[view.ref] = view
    for item in evidence.values():
        if item.conversation_id is None and "message" in item.kind:
            if item.label in incident.conversation_ids:
                item.conversation_id = item.label
            elif item.ref.startswith("message:"):
                item.conversation_id = item.ref.split(":", 2)[1]
    episodes = []
    for archived in session.scalars(select(RiskEpisodeRow).where(
        RiskEpisodeRow.alert_id.in_([s.alert_id for s in incident.signals])
    ).order_by(RiskEpisodeRow.closed_at.desc())):
        snapshot = json.loads(archived.snapshot_json)
        episodes.append(RiskEpisodeView(
            alert_id=archived.alert_id, episode=archived.episode,
            risk_type=snapshot["riskType"], risk_level=snapshot["riskLevel"],
            status=snapshot["riskStatus"], closed_at=archived.closed_at.replace(tzinfo=UTC).isoformat(),
            handled_by=snapshot.get("handledBy"), handled_note=snapshot.get("handledNote"),
            rule_version=snapshot.get("ruleVersion", "legacy"),
            evidence=[RiskEvidenceView.model_validate(e) for e in snapshot.get("evidence", [])],
        ))
    return RiskIncidentDetailView(
        incident=incident, contexts=contexts, evidence=list(evidence.values()),
        tickets=[t for t in list_tickets(session) if t.ticket_id in incident.work_order_ids],
        handling_history=sorted({
            event.event_id: event for old_id in history_ids for event in events_for(session, old_id)
        }.values(), key=lambda e: e.created_at, reverse=True),
        episodes=episodes,
        service_breakpoint_assessments=[read_assessment(session, cid) for cid in incident.conversation_ids],
        judgment_history=judgment_history(session, [signal.alert_id for signal in incident.signals]),
        contact_history=sorted(contact_history.values(), key=lambda item: item.occurred_at or ""),
        emotion_history=_emotion_history(session, incident.primary_conversation_id or incident.conversation_ids[0]),
        service_points=_service_points(
            session, [incident.primary_conversation_id or incident.conversation_ids[0]],
        ),
        emotion_comparisons=_emotion_comparisons(
            session, incident.conversation_ids,
            incident.primary_conversation_id or incident.conversation_ids[0],
        ),
    )


def update_incident(
    session: Session, incident_id: str, status: str, note: str, expected_version: str,
    *, actor: str = DEFAULT_OPERATOR,
):
    session.execute(update(DatasetRow).values(active_batch_id=DatasetRow.active_batch_id))
    detail = incident_detail(session, incident_id)
    if expected_version != detail.incident.version:
        raise ConflictError("风险信号已更新，请刷新后复核")
    if not note.strip():
        raise ValidationRejected("请填写处置说明")
    active = [signal for signal in detail.incident.signals
              if signal.risk_status.value in {"pending", "in_progress"}]
    if detail.incident.current_action in {"intervene", "review"}:
        active = [signal for signal in active if signal.current_attention != "historical"]
    repository = RiskAlertRepository(session)
    if status == "reopen":
        if active:
            raise ValidationRejected("事件仍在处理中")
        for signal in detail.incident.signals:
            repository.reopen(signal.alert_id, actor, note)
        record_event(session, incident_id, "risk", "reopen", note,
                     detail.incident.conversation_ids[0], actor=actor)
        return incident_detail(session, incident_id)
    if not active:
        raise ValidationRejected("该风险已关闭")
    if status == "resolved" and any(
        signal.risk_status.value == "pending" and signal_attention(
            signal.risk_status.value, signal_active=signal.signal_active,
            analysis_stale=bool(signal.conditions.get("analysisStale")),
        ) == "active" for signal in active
    ):
        raise ValidationRejected("仍有正在触发的风险，请先介入处理")
    for signal in active:
        repository.update_status(
            alert_id=signal.alert_id, target=ServiceRiskStatus(status), actor=actor, note=note,
        )
    record_event(session, incident_id, "risk", status, note, detail.incident.conversation_ids[0], actor=actor)
    return incident_detail(session, incident_id)


def intervene(
    session: Session, incident_id: str, conversation_id: str, expected_version: str, *, actor: str,
) -> RiskIncidentDetailView:
    from app.domain.consumer_service.auto_reception import change_mode
    from app.domain.enums import ServiceMode

    session.execute(update(DatasetRow).values(active_batch_id=DatasetRow.active_batch_id))
    detail = incident_detail(session, incident_id)
    if expected_version != detail.incident.version:
        raise ConflictError("风险信号已更新，请刷新后接管")
    if conversation_id not in detail.incident.conversation_ids:
        raise ValidationRejected("该会话不属于此风险事件")
    if risk_service_states(session).get(conversation_id, ("historical", None))[0] != "live":
        raise ValidationRejected("当前无接待中的会话，请查看服务记录或跟进工单")
    signals = [
        signal for signal in detail.incident.signals
        if signal.conversation_id == conversation_id and signal.current_attention == "active"
    ]
    if not signals:
        raise ValidationRejected("该会话暂无需要接管的风险")
    # One transaction changes reception mode, cancels unsent AI jobs and records intervention.
    change_mode(session, conversation_id, ServiceMode.OPERATOR_ASSISTED, actor="operator")
    pending = [signal for signal in signals if signal.risk_status.value == "pending"]
    note = f"接管会话 {conversation_id}"
    repository = RiskAlertRepository(session)
    for signal in pending:
        repository.update_status(
            alert_id=signal.alert_id, target=ServiceRiskStatus.IN_PROGRESS, actor=actor, note=note,
        )
    if pending:
        record_event(session, incident_id, "risk", "in_progress", note, conversation_id, actor=actor)
    session.flush()
    return incident_detail(session, incident_id)


def scan_risks(session: Session) -> RiskScanView:
    from app.domain.consumer_service.risk_rules import evaluate_risks, load_rule_inputs

    batch = active_batch(session)
    if batch is None:
        return RiskScanView(alerts_created=0, incident_count=0)
    repository = RiskAlertRepository(session)
    before = len(repository.list(batch_id=batch))
    evaluate_risks(session, batch_id=batch)
    _, _, reference = load_rule_inputs(session, batch)
    session.flush()
    return RiskScanView(
        alerts_created=len(repository.list(batch_id=batch)) - before,
        incident_count=len(list_incidents(session)),
        reference_time=reference.replace(tzinfo=UTC).isoformat() if isinstance(reference, datetime) else None,
    )
