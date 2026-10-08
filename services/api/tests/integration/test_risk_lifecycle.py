import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from tests.integration import test_reception_workspace as fixtures

from app.domain.consumer_service.models import (
    RiskEpisodeRow,
    RiskLifecycleRow,
    ServiceRiskAlertRow,
    SourceRecordRow,
)
from app.domain.consumer_service.risk import RiskAlertRepository
from app.domain.consumer_service.risk_rules import evaluate_risks
from app.domain.enums import ServiceRiskLevel, ServiceRiskType

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def create_manual(client):
    cid = fixtures._create(client)
    client.post(f"/api/customer/conversations/{cid}/handoff", headers=CUSTOMER)
    return cid


def incident(client, cid):
    response = client.get("/api/support/desk/risks", headers=SUPPORT)
    assert response.status_code == 200, response.text
    return next(row for row in response.json() if cid in row["conversationIds"])


def action(client, record, status, note="人工核实"):
    return client.post(f"/api/support/desk/risks/{record['incidentId']}/status", headers=SUPPORT,
                       json={"status": status, "note": note, "expectedVersion": record["version"]})


def test_recurrence_preserves_closed_evidence_and_does_not_reopen_on_replay(workspace):
    client, factory, provider = workspace
    cid = create_manual(client)
    fixtures._send(client, cid, "请查一下订单", key="baseline")
    fixtures._send(client, cid, "再不处理我就投诉", key="first-risk")
    record = incident(client, cid)
    response = action(client, record, "in_progress")
    assert response.status_code == 200, response.text
    response = action(client, response.json()["incident"], "resolved", "第一轮已核实")
    assert response.status_code == 200, response.text
    assert response.json()["incident"]["attentionState"] == "closed"
    assert response.json()["incident"]["signalActive"] is False
    assert response.json()["incident"]["triageScore"] == 0
    ids = [s["alertId"] for s in response.json()["incident"]["signals"]]
    with factory() as session:
        snapshots = {r.episode_id: r.snapshot_json for r in session.scalars(
            select(RiskEpisodeRow).where(RiskEpisodeRow.alert_id.in_(ids)))}
        assert snapshots
        evaluate_risks(session)
        session.commit()
    assert incident(client, cid)["riskStatus"] == "resolved"
    fixtures._send(client, cid, "现在又没处理好，我要再次投诉", key="second-risk")
    record = incident(client, cid)
    assert record["riskStatus"] == "pending"
    assert record["recurrenceCount"] == 1
    with factory() as session:
        assert {r.episode_id: r.snapshot_json for r in session.scalars(
            select(RiskEpisodeRow).where(RiskEpisodeRow.alert_id.in_(ids)))} == snapshots
        with pytest.raises(IntegrityError):
            session.execute(update(RiskEpisodeRow).values(snapshot_json="{}"))
        session.rollback()
    assert not provider.calls


def test_stale_operator_decision_is_rejected_and_manual_reopen_is_a_new_round(workspace):
    client, _, _ = workspace
    cid = create_manual(client)
    fixtures._send(client, cid, "请看一下", key="b")
    fixtures._send(client, cid, "我要投诉", key="r1")
    stale = incident(client, cid)
    fixtures._send(client, cid, "我还要向平台举报", key="r2")
    assert action(client, stale, "in_progress").status_code == 409
    response = action(client, incident(client, cid), "ignored", "确认本轮不需继续")
    assert response.status_code == 200
    response = action(client, response.json()["incident"], "reopen", "客服重新核实")
    assert response.status_code == 200, response.text
    assert response.json()["incident"]["riskStatus"] == "in_progress"
    assert response.json()["incident"]["recurrenceCount"] == 1
    assert response.json()["episodes"]


def test_ticket_deadline_is_monitored_and_completion_only_requests_review(workspace):
    client, factory, provider = workspace
    cid = create_manual(client)
    response = client.post("/api/support/desk/tickets", headers=SUPPORT, json={
        "title": "物流跟进", "conversationId": cid, "workOrderType": "logistics",
        "assignee": "当前客服", "note": "核对物流",
        "dueAt": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    })
    assert response.status_code == 200, response.text
    ticket = response.json()
    with factory() as session:
        before = {r.record_id: r.row_sha256 for r in session.scalars(select(SourceRecordRow))}
        evaluate_risks(session, now=datetime.now(UTC) + timedelta(hours=2))
        session.commit()
    record = incident(client, cid)
    assert any(s["riskType"] == "work_order_overdue" for s in record["signals"])
    for status in ("in_progress", "resolved"):
        response = client.put(f"/api/support/desk/tickets/{ticket['ticketId']}", headers=SUPPORT,
                              json={"expectedRevision": ticket["revision"], "status": status,
                                    "priority": "normal", "assignee": "当前客服", "note": "已跟进"})
        assert response.status_code == 200, response.text
        ticket = response.json()
    record = incident(client, cid)
    assert record["riskStatus"] == "pending"
    assert record["needsReview"] is True
    assert record["signalActive"] is False
    closed = action(client, record, "resolved", "触发条件已消退，人工复核关闭")
    assert closed.status_code == 200, closed.text
    assert closed.json()["incident"]["riskStatus"] == "resolved"
    assert closed.json()["incident"]["attentionState"] == "closed"
    assert closed.json()["incident"]["needsReview"] is False
    with factory() as session:
        assert {r.record_id: r.row_sha256 for r in session.scalars(select(SourceRecordRow))} == before
    assert not provider.calls


def test_repeated_scans_do_not_reorder_or_duplicate_unchanged_signals(workspace):
    _client, factory, _ = workspace
    with factory() as session:
        evaluate_risks(session)
        session.commit()
        before = {r.alert_id: r.updated_at for r in session.scalars(select(ServiceRiskAlertRow))}
    with factory() as session:
        evaluate_risks(session)
        session.commit()
        after = {r.alert_id: r.updated_at for r in session.scalars(select(ServiceRiskAlertRow))}
    assert after == before


def test_corrected_order_association_keeps_previous_handling_history(workspace):
    client, _, _ = workspace
    cid = create_manual(client)
    fixtures._send(client, cid, "请查记录", key="b")
    fixtures._send(client, cid, "我要投诉", key="r")
    response = action(client, incident(client, cid), "in_progress", "关联订单前已介入")
    assert response.status_code == 200
    source = client.get("/api/support/conversations/S00001/service-context", headers=SUPPORT).json()
    order_id = source["orders"][0]["orderId"]
    fixtures._send(client, cid, f"订单{order_id}，还没处理，我继续投诉", key="order-link")
    record = incident(client, cid)
    detail = client.get(f"/api/support/desk/risks/{record['incidentId']}", headers=SUPPORT).json()
    assert order_id in record["orderIds"]
    assert any(e["note"] == "关联订单前已介入" for e in detail["handlingHistory"])


def test_stale_analysis_is_review_only_in_dashboard_and_reception(workspace):
    client, factory, provider = workspace
    cid = create_manual(client)
    fixtures._send(client, cid, "查询物流进度", key="baseline")
    source = client.get(f"/api/support/conversations/{cid}/service-context", headers=SUPPORT).json()
    with factory() as session:
        repository = RiskAlertRepository(session)
        row = repository.sync_from_assistant(
            batch_id=source["batchId"], conversation_id=cid, buyer_alias="显式测试消费者",
            risk_types=[ServiceRiskType.SERVICE_BREAKPOINT], risk_level=ServiceRiskLevel.HIGH,
            risk_reason="已过期的断点分析", evidence_refs=[],
        )[0]
        metadata = repository._lifecycle(row)
        metadata.conditions_json = json.dumps({"analysisStale": True})
        session.commit()
    record = incident(client, cid)
    assert record["attentionState"] == "review" and record["signalActive"] is False
    assert record["triageLabel"] == "review"
    queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()["items"]
    item = next(item for item in queue if item["conversationId"] == cid)
    assert item["riskLevel"] is None and item["activeRiskTypes"] == []
    assert item["reviewRiskTypes"] == ["service_breakpoint"]
    assert not provider.calls


def test_legacy_history_is_separate_from_detection_and_judgment_evidence(workspace):
    client, factory, provider = workspace
    source = client.get("/api/support/conversations/S00146/service-context", headers=SUPPORT).json()
    record = incident(client, "S00146")
    assert record["latestMessage"] == "嗯，这还差不多"
    assert record["currentEmotion"] == "calm" and record["attentionState"] == "review"
    assert record["signalActive"] is False
    refs = [source["workOrders"][0]["sourceRecordId"]]
    with factory() as session:
        repository = RiskAlertRepository(session)
        row = repository.sync_from_assistant(
            batch_id=source["batchId"], conversation_id="S00146", buyer_alias=source["buyerAlias"],
            risk_types=[ServiceRiskType.REPEATED_CONTACT], risk_level=ServiceRiskLevel.MEDIUM,
            risk_reason="旧版本重复进线", evidence_refs=refs,
            order_id=source["orders"][0]["orderId"],
        )[0]
        metadata = repository._lifecycle(row)
        metadata.rule_version = "legacy"
        metadata.signal_active = False
        alert_id = row.alert_id
        session.commit()
    record = incident(client, "S00146")
    detail = client.get(f"/api/support/desk/risks/{record['incidentId']}", headers=SUPPORT).json()
    signal = next(signal for signal in detail["incident"]["signals"] if signal["alertId"] == alert_id)
    assert signal["evidenceRefs"] == refs and signal["conditions"] == {}
    assert len(detail["contactHistory"]) >= 2
    assert all(item["kind"] == "history_context" for item in detail["contactHistory"])
    with factory() as session:
        assert json.loads(session.get(ServiceRiskAlertRow, alert_id).evidence_refs_json) == refs
        assert json.loads(session.get(RiskLifecycleRow, alert_id).conditions_json) == {}
    assert not provider.calls
