from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures
from tests.integration import test_risk_lifecycle as lifecycle

from app.domain.case_state.models import AuditEventRow, MessageRow
from app.domain.consumer_service.assistant import _risk_summary
from app.domain.consumer_service.auto_reception import process_job
from app.domain.consumer_service.models import AutoReplyJobRow, SourceRecordRow
from app.domain.consumer_service.risk_rules import evaluate_risks
from app.domain.enums import ServiceRiskType

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT


def simulate_wait(factory, message_id):
    # Fixture clock only: no sleep or changes to the main runtime.
    with factory() as session:
        target = session.get(MessageRow, message_id)
        for message in session.scalars(select(MessageRow).where(
            MessageRow.conversation_id == target.conversation_id,
            MessageRow.applies_to_message_revision <= target.applies_to_message_revision,
        )):
            message.created_at -= timedelta(minutes=3)
        evaluate_risks(session)
        session.commit()


def queue_item(client, cid):
    response = client.get("/api/support/reception/queue", headers=SUPPORT)
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["conversationId"] == cid)


def test_manual_reply_clears_precomplaint_wait_but_risk_needs_review(workspace):
    client, factory, provider = workspace
    cid = lifecycle.create_manual(client)
    message = fixtures._send(client, cid, "请核对物流", key="waiting")["message"]
    simulate_wait(factory, message["messageId"])
    record = lifecycle.incident(client, cid)
    assert {signal["riskType"] for signal in record["signals"]} == {"response_wait"}
    assert record["currentEmotion"] == "calm" and record["attentionState"] == "active"
    assert queue_item(client, cid)["activeRiskTypes"] == ["response_wait"]
    with factory() as session:
        evaluate_risks(session)
        session.commit()
    assert lifecycle.incident(client, cid)["version"] == record["version"]
    response = client.post(f"/api/support/reception/{cid}/messages", headers=SUPPORT, json={
        "body": "我来核对这笔订单的物流记录。", "clientMessageKey": "actual-reply",
    })
    assert response.status_code == 200, response.text
    record = lifecycle.incident(client, cid)
    assert record["riskStatus"] == "pending" and record["attentionState"] == "review"
    assert queue_item(client, cid)["activeRiskTypes"] == []
    assert queue_item(client, cid)["reviewRiskTypes"] == ["response_wait"]
    with factory() as session:
        assert _risk_summary(session, cid)[0] == [ServiceRiskType.UNKNOWN]
    closed = lifecycle.action(client, record, "resolved", "已核对实际回复")
    assert closed.status_code == 200, closed.text
    assert closed.json()["incident"]["attentionState"] == "closed"
    assert not provider.calls


def test_delivered_ai_reply_is_recognized_by_the_next_risk_tick(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    message = fixtures._send(client, cid)["message"]
    simulate_wait(factory, message["messageId"])
    assert queue_item(client, cid)["activeRiskTypes"] == ["response_wait"]
    with factory() as session:
        job = session.scalar(select(AutoReplyJobRow).where(AutoReplyJobRow.conversation_id == cid))
        job_id = job.job_id
    process_job(client.app.state.runtime, job_id)
    with factory() as session:
        assert session.get(AutoReplyJobRow, job_id).status == "sent"
    assert queue_item(client, cid)["activeRiskTypes"] == []
    assert queue_item(client, cid)["reviewRiskTypes"] == ["response_wait"]
    assert len(provider.calls) == 2


def test_due_soon_completion_and_real_reschedule_keep_independent_risk_history(workspace):
    client, factory, provider = workspace
    cid = lifecycle.create_manual(client)
    due = (datetime.now(UTC) + timedelta(minutes=20)).isoformat()
    with factory() as session:
        originals = {row.record_id: row.row_sha256 for row in session.scalars(select(SourceRecordRow))}
    response = client.post("/api/support/desk/tickets", headers=SUPPORT, json={
        "title": "物流跟进", "conversationId": cid, "workOrderType": "logistics",
        "assignee": "G001", "note": "约定反馈物流", "dueAt": due,
    })
    assert response.status_code == 200, response.text
    ticket = response.json()
    record = lifecycle.incident(client, cid)
    assert {signal["riskType"] for signal in record["signals"]} == {"followup_due_soon"}
    assert record["attentionState"] == "active"
    handled = lifecycle.action(client, record, "in_progress", "核对临期提醒")
    assert handled.status_code == 200, handled.text
    closed = lifecycle.action(client, handled.json()["incident"], "resolved", "本次提醒已确认")
    assert closed.status_code == 200, closed.text

    path = f"/api/support/desk/tickets/{ticket['ticketId']}"
    payload = {
        "expectedRevision": ticket["revision"], "status": "in_progress", "priority": "normal",
        "assignee": "G001", "dueAt": due, "note": "普通备注不更改期限",
    }
    noted = client.put(path, headers=SUPPORT, json=payload)
    assert noted.status_code == 200, noted.text
    assert lifecycle.incident(client, cid)["riskStatus"] == "resolved"

    changed_due = (datetime.now(UTC) + timedelta(minutes=25)).isoformat()
    payload.update(expectedRevision=noted.json()["revision"], dueAt=changed_due, note="明确改期")
    rescheduled = client.put(path, headers=SUPPORT, json=payload)
    assert rescheduled.status_code == 200, rescheduled.text
    record = lifecycle.incident(client, cid)
    assert record["riskStatus"] == "pending" and record["recurrenceCount"] == 1
    assert record["signals"][0]["conditions"]["deadlines"][0]["dueAt"]
    payload.update(expectedRevision=rescheduled.json()["revision"], status="resolved", note="本地跟进完成")
    completed = client.put(path, headers=SUPPORT, json=payload)
    assert completed.status_code == 200, completed.text
    record = lifecycle.incident(client, cid)
    assert record["riskStatus"] == "pending" and record["attentionState"] == "review"
    with factory() as session:
        events = list(session.scalars(select(AuditEventRow).where(
            AuditEventRow.conversation_id == cid, AuditEventRow.event_type == "ticket_deadline_changed",
        )))
        assert len(events) == 2
        assert {row.record_id: row.row_sha256 for row in session.scalars(select(SourceRecordRow))} == originals
    assert not provider.calls
