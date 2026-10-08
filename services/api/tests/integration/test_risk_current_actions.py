from datetime import UTC, datetime, timedelta

from tests.integration import test_reception_workspace as fixtures

from app.domain.case_state.models import ConversationRow
from app.domain.enums import CaseStatus
from app.repositories.conversation_repository import ConversationRepository

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def records(client, cid):
    response = client.get(f"/api/support/desk/conversations/{cid}/risks", headers=SUPPORT)
    assert response.status_code == 200, response.text
    return response.json()


def close_service(factory, cid):
    with factory() as session:
        repo = ConversationRepository(session)
        case, _ = repo.create_case_for_conversation(session.get(ConversationRow, cid))
        repo.set_case_status(case, CaseStatus.CLOSED, actor_type="operator")
        session.commit()


def followup(client, cid):
    response = client.post("/api/support/desk/tickets", headers=SUPPORT, json={
        "title": "取件结果跟进", "conversationId": cid, "workOrderType": "logistics",
        "assignee": "G001", "note": "核对取件结果",
        "dueAt": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
    })
    assert response.status_code == 200, response.text
    return response.json()


def queue_item(client, cid):
    response = client.get("/api/support/reception/queue", headers=SUPPORT)
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["conversationId"] == cid)


def test_s00146_history_displays_calm_feedback_and_actual_emotion_sequence(workspace):
    client, _, provider = workspace
    items = records(client, "S00146")
    assert items
    assert all(item["currentAction"] == "record_only" and item["triageScore"] == 0 for item in items)
    record = next(item for item in items if "S00146" in item["conversationIds"])
    assert record["currentEmotion"] == "calm"
    response = client.get(f"/api/support/desk/risks/{record['incidentId']}", headers=SUPPORT)
    assert response.status_code == 200, response.text
    trail = response.json()["emotionHistory"]
    assert trail[-1]["body"] == "嗯，这还差不多" and trail[-1]["emotion"] == "calm"
    assert any(point["emotion"] == "angry" for point in trail[:-1])
    assert all(point["occurredAt"].endswith("+00:00") for point in trail)
    assert queue_item(client, "S00146")["activeRiskTypes"] == []
    assert not provider.calls


def test_new_followup_on_source_conversation_is_live_without_local_chat(workspace):
    client, factory, provider = workspace
    ticket = followup(client, "S00146")
    with factory() as session:
        assert session.get(ConversationRow, "S00146") is None
    record = next(item for item in records(client, "S00146") if any(
        signal["riskType"] == "followup_due_soon" for signal in item["signals"]
    ))
    assert record["currentAction"] == "intervene"
    assert record["serviceState"] == "live"
    assert ticket["ticketId"] in record["workOrderIds"]
    assert "followup_due_soon" in queue_item(client, "S00146")["activeRiskTypes"]
    assert not provider.calls


def test_closed_calm_service_remains_reviewable_without_requesting_intervention(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    client.post(f"/api/customer/conversations/{cid}/handoff", headers=CUSTOMER)
    fixtures._send(client, cid, "查询订单", "baseline")
    fixtures._send(client, cid, "我要投诉", "complaint")
    fixtures._send(client, cid, "已经解决了，谢谢", "relief")
    close_service(factory, cid)
    record = records(client, cid)[0]
    assert record["serviceState"] == "closed"
    assert record["currentAction"] == "review"
    assert record["currentEmotion"] == "calm" and record["emotionTrend"] == "falling"
    assert record["riskStatus"] == "pending" and record["signalActive"] is False
    closed = client.post(f"/api/support/desk/risks/{record['incidentId']}/status",
                         headers=SUPPORT, json={
                             "status": "resolved", "note": "核对消费者反馈，问题已解决",
                             "expectedVersion": record["version"],
                         })
    assert closed.status_code == 200, closed.text
    assert closed.json()["incident"]["currentAction"] == "none"
    assert not provider.calls


def test_chat_closure_does_not_hide_independent_due_followup(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    client.post(f"/api/customer/conversations/{cid}/handoff", headers=CUSTOMER)
    fixtures._send(client, cid, "好的，谢谢", "ack")
    ticket = followup(client, cid)
    before = records(client, cid)[0]
    close_service(factory, cid)
    record = records(client, cid)[0]
    assert record["serviceState"] == "closed" and record["currentAction"] == "intervene"
    assert record["version"] != before["version"]
    assert record["openTicketCount"] == 1 and ticket["ticketId"] in record["workOrderIds"]
    assert "followup_due_soon" in queue_item(client, cid)["activeRiskTypes"]
    assert not provider.calls
