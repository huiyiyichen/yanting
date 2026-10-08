import json

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from tests.integration import test_reception_workspace as fixtures
from tests.integration import test_risk_lifecycle as lifecycle

from app.domain.consumer_service.models import RiskJudgmentRow, SourceRecordRow
from app.domain.consumer_service.risk_rules import evaluate_risks

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def setup_signal(client):
    cid = lifecycle.create_manual(client)
    fixtures._send(client, cid, "请核对已有记录", key="baseline")
    fixtures._send(client, cid, "还是没处理，我要投诉", key="complaint")
    record = lifecycle.incident(client, cid)
    signal = next(item for item in record["signals"] if item["riskType"] == "complaint_risk")
    return cid, record, signal


def judge(client, record, signal, verdict="confirmed", note="核对消费者实际诉求", previous=None, headers=None):
    return client.post(
        f"/api/support/desk/risks/{record['incidentId']}/signals/{signal['alertId']}/judgment",
        headers=headers or SUPPORT,
        json={"verdict": verdict, "note": note, "expectedVersion": record["version"],
              "expectedJudgmentId": previous},
    )


def test_judgment_is_persisted_without_changing_risk_tickets_or_source_facts(workspace):
    client, factory, provider = workspace
    _, record, signal = setup_signal(client)
    before_tickets = client.get("/api/support/desk/tickets", headers=SUPPORT).json()
    with factory() as session:
        before_sources = {row.record_id: row.values_json for row in session.scalars(select(SourceRecordRow))}
    result = judge(client, record, signal, verdict="false_positive",
                   headers={**SUPPORT, "X-Demo-Operator": "G002"})
    assert result.status_code == 200, result.text
    detail = result.json()
    assert detail["incident"]["riskStatus"] == record["riskStatus"]
    assert detail["incident"]["version"] != record["version"]
    before = next(item for item in record["signals"] if item["alertId"] == signal["alertId"])
    after = next(item for item in detail["incident"]["signals"] if item["alertId"] == signal["alertId"])
    assert after["currentAttention"] == "historical"
    assert {key: value for key, value in before.items() if key != "currentAttention"} == {
        key: value for key, value in after.items() if key != "currentAttention"
    }
    judgment = detail["incident"]["judgments"][0]
    assert judgment["actor"] == "G002"
    assert judgment["verdict"] == "false_positive"
    assert judgment["stale"] is False
    assert judgment["evidence"] and judgment["evidenceRefs"]
    assert any("我要投诉" in item["body"] for item in judgment["evidence"])
    persisted = client.get(f"/api/support/desk/risks/{record['incidentId']}", headers=SUPPORT).json()
    assert persisted["judgmentHistory"] == detail["judgmentHistory"]
    assert client.get("/api/support/desk/tickets", headers=SUPPORT).json() == before_tickets
    with factory() as session:
        assert {row.record_id: row.values_json for row in session.scalars(select(SourceRecordRow))} == before_sources
    assert not provider.calls


def test_false_positive_leaves_current_queue_until_new_evidence_or_explicit_restore(workspace):
    client, _, provider = workspace
    cid, record, signal = setup_signal(client)
    response = judge(client, record, signal, "false_positive")
    current = response.json()["incident"]
    latest = next(item for item in current["judgments"] if item["alertId"] == signal["alertId"])
    queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()
    item = next(row for row in queue["items"] if row["conversationId"] == cid)
    assert "complaint_risk" not in item["activeRiskTypes"]
    restored = judge(client, current, signal, "confirmed", previous=latest["judgmentId"])
    assert restored.status_code == 200, restored.text
    current = restored.json()["incident"]
    latest = next(item for item in current["judgments"] if item["alertId"] == signal["alertId"])
    dismissed = judge(client, current, signal, "false_positive", previous=latest["judgmentId"])
    assert dismissed.status_code == 200
    fixtures._send(client, cid, "我要向平台举报，请立即处理", key="renewed-risk")
    current = lifecycle.incident(client, cid)
    assert next(item for item in current["judgments"] if item["alertId"] == signal["alertId"])["stale"]
    assert next(item for item in current["signals"] if item["alertId"] == signal["alertId"])["currentAttention"] == "active"
    assert not provider.calls

def test_corrections_append_history_and_old_judgment_id_cannot_overwrite(workspace):
    client, factory, provider = workspace
    _, record, signal = setup_signal(client)
    first = judge(client, record, signal).json()["incident"]["judgments"][0]
    second = judge(client, record, signal, "insufficient", "还需核对不同诉求",
                   previous=first["judgmentId"])
    assert second.status_code == 200, second.text
    detail = second.json()
    latest = detail["incident"]["judgments"][0]
    assert latest["supersedesId"] == first["judgmentId"]
    assert latest["verdict"] == "insufficient"
    assert len(detail["judgmentHistory"]) == 2
    assert judge(client, record, signal, previous=first["judgmentId"]).status_code == 409
    assert judge(client, record, signal).status_code == 409
    with factory() as session:
        original = session.get(RiskJudgmentRow, first["judgmentId"])
        assert original.note == first["note"] and original.verdict == "confirmed"
        for statement in [update(RiskJudgmentRow).values(note="changed"), delete(RiskJudgmentRow)]:
            with pytest.raises(IntegrityError):
                session.execute(statement)
            session.rollback()
    assert not provider.calls


def test_new_evidence_stales_the_judgment_and_rejects_old_incident_version(workspace):
    client, _, provider = workspace
    cid, record, signal = setup_signal(client)
    first = judge(client, record, signal).json()["incident"]["judgments"][0]
    fixtures._send(client, cid, "我还要向平台举报，请处理", key="new-complaint")
    current = lifecycle.incident(client, cid)
    assert current["judgments"][0]["stale"] is True
    assert judge(client, record, signal, previous=first["judgmentId"]).status_code == 409
    refreshed = judge(client, current, signal, previous=first["judgmentId"])
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["incident"]["judgments"][0]["stale"] is False
    old = next(row for row in refreshed.json()["judgmentHistory"] if row["judgmentId"] == first["judgmentId"])
    assert old["stale"] and old["evidence"] == first["evidence"]
    assert not provider.calls


def test_handling_and_unchanged_scans_do_not_invalidate_a_judgment_but_new_round_does(workspace):
    client, factory, provider = workspace
    _, record, signal = setup_signal(client)
    first = judge(client, record, signal).json()["incident"]["judgments"][0]
    with factory() as session:
        evaluate_risks(session)
        session.commit()
    for status in ["in_progress", "resolved"]:
        response = lifecycle.action(client, record, status)
        assert response.status_code == 200, response.text
        record = response.json()["incident"]
        assert record["judgments"][0]["stale"] is False
    reopened = lifecycle.action(client, record, "reopen").json()
    assert reopened["incident"]["judgments"][0]["stale"] is True
    assert reopened["incident"]["judgments"][0]["judgmentId"] == first["judgmentId"]
    assert reopened["incident"]["recurrenceCount"] == 1
    assert not provider.calls


@pytest.mark.parametrize("verdict,note,status", [
    ("confirmed", "   ", 422), ("resolved", "不能关闭风险", 422),
])
def test_invalid_or_empty_judgments_are_rejected(workspace, verdict, note, status):
    client, _, _ = workspace
    _, record, signal = setup_signal(client)
    response = judge(client, record, signal, verdict, note)
    assert response.status_code == status
    if verdict == "confirmed":
        assert response.json()["detail"][0]["loc"] == ["body", "note"]


def test_customer_and_unknown_operator_cannot_write_judgments(workspace):
    client, _, provider = workspace
    _, record, signal = setup_signal(client)
    assert judge(client, record, signal, headers=CUSTOMER).status_code == 403
    response = judge(client, record, signal, headers={**SUPPORT, "X-Demo-Operator": "UNKNOWN"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_rejected"
    assert client.get("/api/support/desk/risk-judgments/export", headers=CUSTOMER).status_code == 403
    assert not provider.calls


def test_export_preserves_snapshot_and_discloses_positive_only_demo_annotations(workspace):
    client, factory, provider = workspace
    _, record, signal = setup_signal(client)
    first = judge(client, record, signal).json()["incident"]["judgments"][0]
    result = client.get("/api/support/desk/risk-judgments/export", headers=SUPPORT)
    assert result.status_code == 200, result.text
    exported = result.json()
    assert exported["annotationScope"] == "demo_operator"
    assert exported["samplingScope"] == "detected_signals_only"
    assert exported["independentlyValidated"] is False
    assert exported["judgments"] == [first]
    with factory() as session:
        stored = session.get(RiskJudgmentRow, first["judgmentId"])
        snapshot = json.loads(stored.snapshot_json)
        assert exported["batchId"] == stored.batch_id
        assert snapshot["evidence"] == first["evidence"]
        assert snapshot["conditions"] == first["conditions"]
    assert not provider.calls


def test_judgment_cannot_be_attached_to_an_unrelated_incident(workspace):
    client, _, _ = workspace
    _, first, _ = setup_signal(client)
    _, _, other_signal = setup_signal(client)
    assert judge(client, first, other_signal).status_code == 404
