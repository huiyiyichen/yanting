"""风险预警存储、状态机与客服处理边界。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditContext, AuditRecorder, summarize
from app.domain.case_state.models import ConversationRow, MessageRow
from app.domain.consumer_service.emotion import (
    CustomerMessage,
    Escalation,
    has_complaint_signal,
    level_of,
)
from app.domain.consumer_service.mapping import DATASET_ID
from app.domain.consumer_service.models import (
    DatasetRow,
    ImportBatchRow,
    RiskEpisodeRow,
    RiskLifecycleRow,
    ServiceConversationRow,
    ServiceMessageRow,
    ServiceRiskAlertRow,
    WorkOrderRow,
)
from app.domain.enums import ServiceRiskLevel, ServiceRiskStatus, ServiceRiskType
from app.errors import NotFoundError, ValidationRejected
from app.schemas.consumer_service import RiskAlertView
from app.schemas.service_desk import RiskJudgmentView

_STATUS_TRANSITIONS: dict[ServiceRiskStatus, set[ServiceRiskStatus]] = {
    ServiceRiskStatus.PENDING: {
        ServiceRiskStatus.IN_PROGRESS,
        ServiceRiskStatus.RESOLVED,
        ServiceRiskStatus.IGNORED,
    },
    ServiceRiskStatus.IN_PROGRESS: {
        ServiceRiskStatus.RESOLVED,
        ServiceRiskStatus.IGNORED,
    },
    ServiceRiskStatus.RESOLVED: set(),
    ServiceRiskStatus.IGNORED: set(),
}

_RECOMMENDED_ACTIONS = {
    ServiceRiskType.EMOTION_ESCALATION: "客服优先回应情绪并核对未完成事项",
    ServiceRiskType.REPEATED_CONTACT: "客服核对历史会话和当前处理进度",
    ServiceRiskType.REPEATED_REFUND: "客服人工核对订单与打款记录",
    ServiceRiskType.ADVERSE_REACTION: "客服优先人工复核不良反应工单",
    ServiceRiskType.ABNORMAL_RETURN: "客服人工核对退货与风控记录",
    ServiceRiskType.WORK_ORDER_OVERDUE: "客服核对工单处理状态",
    ServiceRiskType.COMPLAINT_RISK: "客服优先回应投诉诉求",
    ServiceRiskType.DATA_CONFLICT: "客服核对聊天、订单和工单原始记录",
    ServiceRiskType.SERVICE_BREAKPOINT: "核对消费者实际诉求、历史答复和兑现结果，独立复核服务断点",
    ServiceRiskType.RESPONSE_WAIT: "优先回复消费者当前问题，必要时接管会话",
    ServiceRiskType.FOLLOWUP_DUE_SOON: "在约定时间前核对进展并反馈，需要延后时更新跟进时间",
}


def _alert_id(batch_id: str, conversation_id: str, risk_type: ServiceRiskType) -> str:
    value = uuid.uuid5(
        uuid.NAMESPACE_URL, f"loreal-risk:{batch_id}:{conversation_id}:{risk_type.value}"
    )
    return f"risk-{value.hex[:16]}"


def _now() -> datetime:
    return datetime.now(UTC)


def signal_attention(
    status: str, *, signal_active: bool, analysis_stale: bool = False,
) -> Literal["active", "review", "closed"]:
    if status in {"resolved", "ignored"}:
        return "closed"
    return "active" if signal_active and not analysis_stale else "review"


def current_signal_attention(
    signal: RiskAlertView, *, local_message_ids: set[str], local_ticket_ids: set[str],
    judgment: RiskJudgmentView | None = None,
) -> Literal["active", "review", "closed", "historical"]:
    state = signal_attention(
        signal.risk_status.value, signal_active=signal.signal_active,
        analysis_stale=bool(signal.conditions.get("analysisStale")),
    )
    if state == "closed":
        return state
    if judgment and judgment.verdict == "false_positive" and not judgment.stale:
        return "historical"
    local_evidence = any(
        ref in local_message_ids or ref.rsplit(":", 1)[-1] in local_message_ids
        for ref in signal.evidence_refs
    )
    local_work = bool(local_ticket_ids.intersection(signal.work_order_ids))
    if local_evidence or local_work or (
        signal.risk_status.value == "in_progress" and signal.handled_at
    ):
        return state
    return "historical"


def incident_id_for(row: ServiceRiskAlertRow) -> str:
    key = f"order:{row.order_id}" if row.order_id else f"conversation:{row.conversation_id}"
    return "incident-" + hashlib.sha256(f"{row.batch_id}:{key}".encode()).hexdigest()[:16]


class RiskAlertRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _lifecycle(self, row: ServiceRiskAlertRow) -> RiskLifecycleRow:
        metadata = self._session.get(RiskLifecycleRow, row.alert_id)
        if metadata is None:
            metadata = RiskLifecycleRow(
                alert_id=row.alert_id, episode=1, revision=1,
                order_ids_json=json.dumps([row.order_id] if row.order_id else []),
                work_order_ids_json=json.dumps([row.work_order_id] if row.work_order_id else []),
                rule_version="legacy", fingerprint="", signal_active=True,
                evidence_json="[]", conditions_json="{}",
                incident_ids_json=json.dumps([incident_id_for(row)]),
            )
            self._session.add(metadata)
            self._session.flush()
        return metadata

    def archive_episode(self, row: ServiceRiskAlertRow) -> None:
        metadata = self._lifecycle(row)
        key = f"{row.alert_id}:{metadata.episode}"
        if self._session.get(RiskEpisodeRow, key):
            return
        payload = risk_alert_view(row, self._session).dump()
        payload["evidence"] = json.loads(metadata.evidence_json)
        self._session.add(RiskEpisodeRow(
            episode_id=key, alert_id=row.alert_id, episode=metadata.episode,
            snapshot_json=json.dumps(payload, ensure_ascii=False),
            closed_at=row.handled_at or _now(),
        ))
        self._session.flush()

    def apply_signal(self, batch_id: str, signal: Any) -> ServiceRiskAlertRow:
        from app.domain.consumer_service.risk_rules import RULE_VERSION, utc

        row = self._session.scalar(select(ServiceRiskAlertRow).where(
            ServiceRiskAlertRow.batch_id == batch_id,
            ServiceRiskAlertRow.conversation_id == signal.conversation_id,
            ServiceRiskAlertRow.risk_type == signal.kind.value,
        ))
        if row is None:
            record_id = self._session.scalar(select(ServiceConversationRow.record_id).where(
                ServiceConversationRow.batch_id == batch_id,
                ServiceConversationRow.conversation_id == signal.conversation_id,
            ))
            row = ServiceRiskAlertRow(
                alert_id=_alert_id(batch_id, signal.conversation_id, signal.kind),
                batch_id=batch_id, conversation_record_id=record_id,
                conversation_id=signal.conversation_id, buyer_alias=signal.buyer,
                risk_type=signal.kind.value, risk_level=signal.level.value,
                risk_status=ServiceRiskStatus.PENDING.value,
            )
            self._session.add(row)
            self._session.flush()
        metadata = self._lifecycle(row)
        closed = row.risk_status in {"resolved", "ignored"}
        if closed:
            is_new = (signal.active and row.handled_at is not None
                      and signal.at > utc(row.handled_at)
                      and signal.fingerprint != metadata.fingerprint)
            if not is_new:
                return row
            self.archive_episode(row)
            metadata.episode += 1
            row.risk_status = ServiceRiskStatus.PENDING.value
            row.handled_by = row.handled_note = row.handled_at = None
            AuditRecorder(self._session).record(
                AuditContext.new_turn(actor_type="system", conversation_id=row.conversation_id),
                event_type="risk_recurred",
                detail={"alertId": row.alert_id, "episode": metadata.episode,
                        "evidenceRefs": [e.ref for e in signal.evidence]},
            )
        unchanged = (
            metadata.fingerprint == signal.fingerprint and metadata.signal_active == signal.active
            and metadata.rule_version == RULE_VERSION and row.risk_level == signal.level.value
            and row.trigger_summary == signal.reason
            and metadata.conditions_json == json.dumps(signal.conditions, ensure_ascii=False, sort_keys=True)
        )
        if unchanged:
            return row
        metadata.fingerprint = signal.fingerprint
        metadata.rule_version = RULE_VERSION
        metadata.signal_active = signal.active
        metadata.last_signal_at = signal.at
        metadata.evidence_json = json.dumps([e.dump() for e in signal.evidence], ensure_ascii=False)
        metadata.order_ids_json = json.dumps(sorted(set(signal.order_ids)))
        metadata.work_order_ids_json = json.dumps(sorted(set(signal.ticket_ids)))
        metadata.conditions_json = json.dumps(signal.conditions, ensure_ascii=False, sort_keys=True)
        metadata.revision += 1
        row.order_id = signal.order_ids[0] if len(signal.order_ids) == 1 else None
        row.work_order_id = signal.ticket_ids[0] if len(signal.ticket_ids) == 1 else None
        metadata.incident_ids_json = json.dumps(sorted({
            *json.loads(metadata.incident_ids_json), incident_id_for(row),
        }))
        row.risk_level, row.trigger_summary = signal.level.value, signal.reason
        row.evidence_refs_json = json.dumps([e.ref for e in signal.evidence], ensure_ascii=False)
        row.recommended_action = _RECOMMENDED_ACTIONS[signal.kind]
        row.updated_at = _now()
        self._session.flush()
        return row

    def mark_quiet(self, batch_id: str, detected: set[str]) -> None:
        for row in self.list(batch_id=batch_id):
            if row.alert_id in detected or row.risk_status in {"resolved", "ignored"}:
                continue
            metadata = self._lifecycle(row)
            if metadata.signal_active:
                metadata.signal_active = False
                metadata.revision += 1
                row.updated_at = _now()
            if row.risk_type == ServiceRiskType.RESPONSE_WAIT.value:
                waiting_since = json.loads(metadata.conditions_json).get("waitingSince")
                if not waiting_since:
                    continue
                reply = self._session.scalar(select(MessageRow).where(
                    MessageRow.conversation_id == row.conversation_id,
                    MessageRow.sender_role.in_(["operator", "assistant"]),
                    or_(MessageRow.body != "", MessageRow.attachments_json != "[]"),
                    MessageRow.created_at > datetime.fromisoformat(waiting_since).replace(tzinfo=None),
                ).order_by(MessageRow.applies_to_message_revision.desc()).limit(1))
                if reply is None:
                    continue
                before = row.risk_status
                row.risk_status = ServiceRiskStatus.RESOLVED.value
                row.trigger_summary = row.handled_note = "已回复，等待已结束"
                row.handled_by = "system"
                row.handled_at = reply.created_at
                row.updated_at = _now()
                metadata.revision += 1
                self.archive_episode(row)
                AuditRecorder(self._session).record(
                    AuditContext.new_turn(actor_type="system", conversation_id=row.conversation_id),
                    event_type="risk_status_changed",
                    detail={
                        "alertId": row.alert_id, "riskType": row.risk_type,
                        "fromStatus": before, "toStatus": row.risk_status,
                        "replyMessageId": reply.message_id,
                    },
                )
        self._session.flush()

    def reopen(self, alert_id: str, actor: str, note: str) -> ServiceRiskAlertRow:
        row = self.get(alert_id)
        if row.risk_status not in {"resolved", "ignored"} or not note.strip():
            raise ValidationRejected("仅已关闭风险可重新介入，且必须填写原因")
        self.archive_episode(row)
        metadata = self._lifecycle(row)
        metadata.episode += 1
        metadata.revision += 1
        row.risk_status = ServiceRiskStatus.IN_PROGRESS.value
        row.handled_by, row.handled_note, row.handled_at = actor, note.strip()[:500], _now()
        row.updated_at = _now()
        AuditRecorder(self._session).record(
            AuditContext.new_turn(actor_type="operator", conversation_id=row.conversation_id),
            event_type="risk_reopened",
            detail={"alertId": alert_id, "episode": metadata.episode, "reason": note.strip()[:500]},
        )
        self._session.flush()
        return row

    def active_batch_id(self) -> str:
        dataset = self._session.get(DatasetRow, DATASET_ID)
        if dataset is None:
            raise NotFoundError("尚未发布业务数据")
        batch = self._session.get(ImportBatchRow, dataset.active_batch_id)
        if batch is None:
            raise NotFoundError("业务数据批次不存在")
        return batch.batch_id

    def sync_from_assistant(
        self,
        *,
        batch_id: str,
        conversation_id: str,
        buyer_alias: str,
        risk_types: list[ServiceRiskType],
        risk_level: ServiceRiskLevel,
        risk_reason: str,
        evidence_refs: list[str],
        order_id: str | None = None,
        work_order_id: str | None = None,
        levels: dict[ServiceRiskType, ServiceRiskLevel] | None = None,
    ) -> list[ServiceRiskAlertRow]:
        """写入或更新预警。`levels` 可为个别风险类型指定等级，未指定的用 `risk_level`。"""

        if not risk_types or risk_types == [ServiceRiskType.UNKNOWN]:
            return []
        conversation_record_id = self._session.scalar(
            select(ServiceConversationRow.record_id).where(
                ServiceConversationRow.batch_id == batch_id,
                ServiceConversationRow.conversation_id == conversation_id,
            )
        )
        if (
            conversation_record_id is None
            and self._session.get(ConversationRow, conversation_id) is None
        ):
            raise NotFoundError(f"会话不存在：{conversation_id}")

        result: list[ServiceRiskAlertRow] = []
        for risk_type in risk_types:
            if risk_type is ServiceRiskType.UNKNOWN:
                continue
            type_level = (levels or {}).get(risk_type, risk_level)
            row = self._session.scalar(
                select(ServiceRiskAlertRow).where(
                    ServiceRiskAlertRow.batch_id == batch_id,
                    ServiceRiskAlertRow.conversation_id == conversation_id,
                    ServiceRiskAlertRow.risk_type == risk_type.value,
                )
            )
            if row is None:
                row = ServiceRiskAlertRow(
                    alert_id=_alert_id(batch_id, conversation_id, risk_type),
                    batch_id=batch_id,
                    conversation_record_id=conversation_record_id,
                    conversation_id=conversation_id,
                    buyer_alias=buyer_alias,
                    order_id=order_id,
                    work_order_id=work_order_id,
                    risk_type=risk_type.value,
                    risk_level=type_level.value,
                    risk_status=ServiceRiskStatus.PENDING.value,
                    trigger_summary=risk_reason,
                    evidence_refs_json=json.dumps(evidence_refs, ensure_ascii=False),
                    recommended_action=_RECOMMENDED_ACTIONS[risk_type],
                )
                self._session.add(row)
            else:
                # Compatibility writers cannot overwrite closed evidence or reopen without a new trigger.
                if row.risk_status in {"resolved", "ignored"}:
                    result.append(row)
                    continue
                row.risk_level = type_level.value
                row.trigger_summary = risk_reason
                row.evidence_refs_json = json.dumps(evidence_refs, ensure_ascii=False)
                row.updated_at = _now()
            result.append(row)
        self._session.flush()
        return result

    def list(
        self,
        *,
        batch_id: str,
        risk_type: ServiceRiskType | None = None,
        risk_level: ServiceRiskLevel | None = None,
        risk_status: ServiceRiskStatus | None = None,
    ) -> list[ServiceRiskAlertRow]:
        query = select(ServiceRiskAlertRow).where(ServiceRiskAlertRow.batch_id == batch_id)
        if risk_type is not None:
            query = query.where(ServiceRiskAlertRow.risk_type == risk_type.value)
        if risk_level is not None:
            query = query.where(ServiceRiskAlertRow.risk_level == risk_level.value)
        if risk_status is not None:
            query = query.where(ServiceRiskAlertRow.risk_status == risk_status.value)
        return list(
            self._session.scalars(
                query.order_by(
                    ServiceRiskAlertRow.updated_at.desc(),
                    ServiceRiskAlertRow.alert_id.asc(),
                )
            )
        )

    def get(self, alert_id: str) -> ServiceRiskAlertRow:
        row = self._session.get(ServiceRiskAlertRow, alert_id)
        if row is None:
            raise NotFoundError(f"风险预警不存在：{alert_id}")
        return row

    def update_status(
        self,
        *,
        alert_id: str,
        target: ServiceRiskStatus,
        actor: str,
        note: str,
    ) -> ServiceRiskAlertRow:
        row = self.get(alert_id)
        current = ServiceRiskStatus(row.risk_status)
        if target is current:
            return row
        if target not in _STATUS_TRANSITIONS[current]:
            raise ValidationRejected(f"风险状态不能从 {current.value} 变更为 {target.value}")
        if target in {ServiceRiskStatus.RESOLVED, ServiceRiskStatus.IGNORED} and not note.strip():
            raise ValidationRejected("已处理或已忽略必须填写处理说明")
        if current is ServiceRiskStatus.PENDING and target is ServiceRiskStatus.RESOLVED:
            metadata = self._lifecycle(row)
            if signal_attention(
                current.value, signal_active=metadata.signal_active,
                analysis_stale=bool(json.loads(metadata.conditions_json).get("analysisStale")),
            ) == "active":
                raise ValidationRejected("仍有正在触发的风险，请先介入处理")

        before = current.value
        row.risk_status = target.value
        row.handled_by = actor
        row.handled_at = _now()
        row.handled_note = note.strip()[:500]
        row.updated_at = _now()
        self._lifecycle(row).revision += 1
        if target in {ServiceRiskStatus.RESOLVED, ServiceRiskStatus.IGNORED}:
            self.archive_episode(row)
        AuditRecorder(self._session).record(
            AuditContext.new_turn(
                actor_type="operator",
                conversation_id=row.conversation_id,
            ),
            event_type="risk_status_changed",
            risk_level=row.risk_level,
            human_confirmation_status=target.value,
            detail={
                "alertId": row.alert_id,
                "riskType": row.risk_type,
                "fromStatus": before,
                "toStatus": target.value,
                "handledBy": actor,
                "handledNote": note.strip()[:120],
            },
        )
        self._session.flush()
        return row


def seed_rule_alerts(session: Session, batch_id: str) -> int:
    """为已导入批次建立可回读的规则预警，不调用模型。"""

    from app.domain.consumer_service.risk_rules import evaluate_risks
    repository = RiskAlertRepository(session)
    before_total = len(repository.list(batch_id=batch_id))
    evaluate_risks(session, batch_id=batch_id)
    session.flush()
    return len(repository.list(batch_id=batch_id)) - before_total


def active_batch_id(session: Session) -> str | None:
    dataset = session.get(DatasetRow, DATASET_ID)
    return dataset.active_batch_id if dataset else None


def customer_messages_for(
    session: Session, batch_id: str | None, conversation_id: str
) -> list[CustomerMessage]:
    """会话内全部消费者消息：先导入的历史消息，再本地新消息。

    导入消息的引用用源记录 ID，与其它预警证据一致；本地消息用消息 ID。
    """

    imported = (
        session.scalars(
            select(ServiceMessageRow)
            .where(
                ServiceMessageRow.batch_id == batch_id,
                ServiceMessageRow.conversation_id == conversation_id,
                ServiceMessageRow.sender_role == "customer",
            )
            .order_by(ServiceMessageRow.sent_at, ServiceMessageRow.sequence)
        )
        if batch_id
        else []
    )
    local = session.scalars(
        select(MessageRow)
        .where(MessageRow.conversation_id == conversation_id, MessageRow.sender_role == "customer")
        .order_by(MessageRow.applies_to_message_revision)
    )
    return [CustomerMessage(row.source_record_id, row.body or "") for row in imported] + [
        CustomerMessage(row.message_id, row.body or "") for row in local
    ]


def escalation_level(escalation: Escalation) -> ServiceRiskLevel:
    """升级到要向平台或第三方投诉时为高，其余为中。"""

    if has_complaint_signal(escalation.trigger.body):
        return ServiceRiskLevel.HIGH
    return ServiceRiskLevel.MEDIUM


def escalation_reason(escalation: Escalation) -> str:
    return (
        f"消费者情绪由{level_of(escalation.from_score).label}升级为愤怒："
        f"“{summarize(escalation.trigger.body, limit=60)}”"
    )


def evaluate_emotion_escalation(
    session: Session, conversation_id: str, *, batch_id: str | None = None
) -> ServiceRiskAlertRow | None:
    """按规则判断会话是否情绪升级，是则写入或更新预警。不调用模型。

    导入时对每个官方会话执行一次，客户发送新消息后对该会话再执行一次。
    没有发布业务批次时无法挂靠预警，直接跳过。
    """

    from app.domain.consumer_service.risk_rules import evaluate_risks

    rows = evaluate_risks(session, batch_id=batch_id)
    return next((row for row in rows if row.conversation_id == conversation_id
                 and row.risk_type == ServiceRiskType.EMOTION_ESCALATION.value), None)


def _detail_value(session: Session, row: WorkOrderRow, key: str) -> str | None:
    from app.domain.consumer_service.models import DETAIL_MODELS

    model = DETAIL_MODELS.get(row.work_order_type)
    if model is None:
        return None
    detail = session.get(model, row.record_id)
    if detail is None:
        return None
    try:
        value = json.loads(detail.fields_json)
    except json.JSONDecodeError:
        return None
    return str(value.get(key)) if isinstance(value, dict) and value.get(key) is not None else None


def risk_alert_view(row: ServiceRiskAlertRow, session: Session | None = None) -> RiskAlertView:
    metadata = session.get(RiskLifecycleRow, row.alert_id) if session is not None else None
    trigger_summary = row.trigger_summary
    if (
        row.risk_type == ServiceRiskType.RESPONSE_WAIT.value
        and metadata is not None
        and not metadata.signal_active
    ):
        trigger_summary = row.handled_note if row.handled_by == "system" else "等待已结束"
    return RiskAlertView(
        alert_id=row.alert_id,
        conversation_id=row.conversation_id,
        buyer_alias=row.buyer_alias,
        order_id=row.order_id,
        work_order_id=row.work_order_id,
        risk_type=ServiceRiskType(row.risk_type),
        risk_level=ServiceRiskLevel(row.risk_level),
        risk_status=ServiceRiskStatus(row.risk_status),
        trigger_summary=trigger_summary,
        evidence_refs=json.loads(row.evidence_refs_json or "[]"),
        recommended_action=row.recommended_action,
        created_at=row.created_at.replace(tzinfo=UTC).isoformat(),
        updated_at=row.updated_at.replace(tzinfo=UTC).isoformat(),
        handled_by=row.handled_by,
        handled_at=row.handled_at.replace(tzinfo=UTC).isoformat() if row.handled_at else None,
        handled_note=row.handled_note,
        episode=metadata.episode if metadata else 1,
        revision=metadata.revision if metadata else 1,
        rule_version=metadata.rule_version if metadata else "legacy",
        signal_active=metadata.signal_active if metadata else True,
        last_signal_at=metadata.last_signal_at.replace(tzinfo=UTC).isoformat()
        if metadata and metadata.last_signal_at else None,
        order_ids=json.loads(metadata.order_ids_json) if metadata else [row.order_id] if row.order_id else [],
        work_order_ids=json.loads(metadata.work_order_ids_json) if metadata else [row.work_order_id] if row.work_order_id else [],
        conditions=json.loads(metadata.conditions_json) if metadata else {},
    )
