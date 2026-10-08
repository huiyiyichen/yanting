"""Retain review snapshots; fresh false positives leave the current attention queue."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit.recorder import AuditContext, AuditRecorder
from app.domain.consumer_service.models import (
    DatasetRow,
    RiskJudgmentRow,
    RiskLifecycleRow,
    ServiceRiskAlertRow,
)
from app.domain.consumer_service.risk import risk_alert_view
from app.domain.consumer_service.workspace import active_batch
from app.errors import ConflictError, NotFoundError, ValidationRejected
from app.schemas.service_desk import (
    RiskJudgmentExportView,
    RiskJudgmentRequest,
    RiskJudgmentView,
)


def _detection(session: Session, row: ServiceRiskAlertRow) -> tuple[dict, str]:
    signal = risk_alert_view(row, session)
    metadata = session.get(RiskLifecycleRow, row.alert_id)
    # Handling revisions and timestamps are not new evidence about correctness.
    payload = {
        "alertId": row.alert_id, "conversationId": row.conversation_id,
        "episode": signal.episode, "riskType": row.risk_type, "riskLevel": row.risk_level,
        "ruleVersion": signal.rule_version, "triggerSummary": row.trigger_summary,
        "signalActive": signal.signal_active, "conditions": signal.conditions,
        "orderIds": signal.order_ids, "workOrderIds": signal.work_order_ids,
        "evidenceRefs": sorted(signal.evidence_refs),
        "evidence": sorted(json.loads(metadata.evidence_json) if metadata else [],
                           key=lambda item: item["ref"]),
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return payload, digest


def _view(session: Session, row: RiskJudgmentRow) -> RiskJudgmentView:
    current = session.get(ServiceRiskAlertRow, row.alert_id)
    snapshot = json.loads(row.snapshot_json)
    return RiskJudgmentView(
        judgment_id=row.judgment_id, alert_id=row.alert_id, episode=row.episode,
        verdict=row.verdict, actor=row.actor, note=row.note,
        detection_hash=row.detection_hash, created_at=row.created_at.replace(tzinfo=UTC).isoformat(),
        stale=current is None or _detection(session, current)[1] != row.detection_hash,
        supersedes_id=row.supersedes_id, risk_type=snapshot["riskType"],
        risk_level=snapshot["riskLevel"], conversation_id=snapshot["conversationId"],
        order_ids=snapshot["orderIds"], work_order_ids=snapshot["workOrderIds"],
        evidence_refs=snapshot["evidenceRefs"], conditions=snapshot["conditions"],
        signal_active=snapshot["signalActive"],
        rule_version=snapshot["ruleVersion"], trigger_summary=snapshot["triggerSummary"],
        evidence=snapshot["evidence"],
    )


def _records(session: Session, alert_ids: list[str]) -> list[RiskJudgmentRow]:
    if not alert_ids:
        return []
    return list(session.scalars(select(RiskJudgmentRow).where(
        RiskJudgmentRow.alert_id.in_(alert_ids),
    ).order_by(RiskJudgmentRow.created_at.desc(), RiskJudgmentRow.judgment_id.desc())))


def latest_judgments(session: Session, alert_ids: list[str]) -> dict[str, RiskJudgmentView]:
    latest = {}
    for row in _records(session, alert_ids):
        if row.alert_id not in latest:
            latest[row.alert_id] = _view(session, row)
    return latest


def judgment_history(session: Session, alert_ids: list[str]) -> list[RiskJudgmentView]:
    return [_view(session, row) for row in _records(session, alert_ids)]


def record_judgment(
    session: Session, incident_id: str, alert_id: str, payload: RiskJudgmentRequest, *, actor: str,
):
    from app.domain.consumer_service.incidents import incident_detail

    session.execute(update(DatasetRow).values(active_batch_id=DatasetRow.active_batch_id))
    detail = incident_detail(session, incident_id)
    if payload.expected_version != detail.incident.version:
        raise ConflictError("风险信号已更新，请刷新后复核")
    if not any(signal.alert_id == alert_id for signal in detail.incident.signals):
        raise NotFoundError("该事件不包含此风险信号")
    latest = next(iter(_records(session, [alert_id])), None)
    if payload.expected_judgment_id != (latest.judgment_id if latest else None):
        raise ConflictError("判断记录已更新，请刷新后复核")
    if not payload.note.strip():
        raise ValidationRejected("请填写判断依据")
    row = session.get(ServiceRiskAlertRow, alert_id)
    snapshot, digest = _detection(session, row)
    refs = set(snapshot["evidenceRefs"])
    # Older compatibility signals may not have a lifecycle evidence snapshot.
    if not snapshot["evidence"]:
        snapshot["evidence"] = [item.dump() for item in detail.evidence if item.ref in refs]
    judgment = RiskJudgmentRow(
        judgment_id=f"judgment-{uuid.uuid4().hex[:16]}", batch_id=row.batch_id,
        alert_id=alert_id, episode=snapshot["episode"], verdict=payload.verdict,
        actor=actor, note=payload.note.strip(), detection_hash=digest,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        supersedes_id=latest.judgment_id if latest else None,
    )
    session.add(judgment)
    AuditRecorder(session).record(
        AuditContext.new_turn(actor_type="operator", conversation_id=row.conversation_id),
        event_type="risk_judgment_recorded",
        detail={"judgmentId": judgment.judgment_id, "alertId": alert_id,
                "episode": judgment.episode, "verdict": payload.verdict,
                "operator": actor, "detectionHash": digest},
    )
    session.flush()
    return incident_detail(session, incident_id)


def export_judgments(session: Session) -> RiskJudgmentExportView:
    batch = active_batch(session)
    rows = session.scalars(select(RiskJudgmentRow).where(
        RiskJudgmentRow.batch_id == batch,
    ).order_by(RiskJudgmentRow.created_at, RiskJudgmentRow.judgment_id)) if batch else []
    return RiskJudgmentExportView(
        generated_at=datetime.now(UTC).isoformat(), batch_id=batch,
        judgments=[_view(session, row) for row in rows],
    )
