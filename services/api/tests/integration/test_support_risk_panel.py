from datetime import timedelta

import pytest
from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures
from tests.integration import test_risk_lifecycle as lifecycle

from app.domain.case_state.models import AuditEventRow, MessageRow
from app.domain.consumer_service.models import ServiceRiskAlertRow, SourceRecordRow
from app.domain.consumer_service.risk_rules import evaluate_risks

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def read_scope(client, conversation_id):
    response = client.get(
        f"/api/support/desk/conversations/{conversation_id}/risks", headers=SUPPORT,
    )
    assert response.status_code == 200, response.text
    return response.json()


def snapshot(factory):
    with factory() as session:
        return {
            "sources": [(row.record_id, row.row_sha256) for row in session.scalars(
                select(SourceRecordRow).order_by(SourceRecordRow.record_id),
            )],
            "risks": [(row.alert_id, row.risk_status, row.updated_at) for row in session.scalars(
                select(ServiceRiskAlertRow).order_by(ServiceRiskAlertRow.alert_id),
            )],
            "messages": [row.message_id for row in session.scalars(select(MessageRow))],
            "audit": [row.audit_event_id for row in session.scalars(select(AuditEventRow))],
        }


def test_scoped_panel_is_read_only_and_reads_current_status_without_ai(workspace):
    client, factory, provider = workspace
    first = lifecycle.create_manual(client)
    second = lifecycle.create_manual(client)
    fixtures._send(client, first, "请查询物流", key="baseline")
    fixtures._send(client, first, "一直没处理，我要投诉", key="complaint")
    fixtures._send(client, second, "另一笔也没处理，我要举报", key="other-complaint")
    before = snapshot(factory)
    rows = read_scope(client, first)
    assert rows and all(first in row["conversationIds"] for row in rows)
    assert not any(second in row["conversationIds"] for row in rows)
    assert rows[0]["attentionState"] == "active" and rows[0]["recommendedAction"]
    assert snapshot(factory) == before
    fixtures._send(client, first, "已经解决了，谢谢", key="relief")
    rows = read_scope(client, first)
    assert rows[0]["attentionState"] == "review"
    assert rows[0]["recommendedAction"] == "核对最新反馈与处理结果，确认后关闭"
    closed = lifecycle.action(client, rows[0], "resolved", "人工核对完成")
    assert closed.status_code == 200, closed.text
    rows = read_scope(client, first)
    assert rows[0]["attentionState"] == "closed"
    assert rows[0]["recommendedAction"] == "无需继续处置"
    assert client.get(
        f"/api/support/desk/conversations/{first}/risks", headers=CUSTOMER,
    ).status_code == 403
    assert client.get(
        "/api/support/desk/conversations/not-existing/risks", headers=SUPPORT,
    ).status_code == 404
    assert not provider.calls


def test_scope_matches_explicit_order_but_never_just_a_buyer_alias(workspace):
    client, factory, provider = workspace
    source = client.get(
        "/api/support/conversations/S00146/service-context", headers=SUPPORT,
    ).json()
    created = client.post("/api/customer/conversations", headers=CUSTOMER, json={
        "customerId": source["buyerAlias"],
    })
    cid = created.json()["conversationId"]
    client.post(f"/api/customer/conversations/{cid}/handoff", headers=CUSTOMER)
    fixtures._send(client, cid, "请查物流", key="without-order")
    assert read_scope(client, cid) == []
    order_id = source["orders"][0]["orderId"]
    fixtures._send(client, cid, f"我问的是订单{order_id}", key="explicit-order")
    before = snapshot(factory)
    rows = read_scope(client, cid)
    assert rows and any("S00146" in row["conversationIds"] for row in rows)
    assert all(order_id in row["orderIds"] or cid in row["conversationIds"] for row in rows)
    assert snapshot(factory) == before
    assert not provider.calls


@pytest.mark.parametrize("sender_role", ["operator", "assistant"])
def test_reply_archives_response_wait_and_next_wait_starts_new_episode(workspace, sender_role):
    client, factory, provider = workspace
    cid = lifecycle.create_manual(client)
    sent = fixtures._send(client, cid, "能帮我看看这单到哪了吗？", key="first-wait")
    with factory() as session:
        customer = session.get(MessageRow, sent["message"]["messageId"])
        customer_at = customer.created_at
        evaluate_risks(session, now=customer_at + timedelta(seconds=150))
        session.commit()
    waiting = next(signal for row in read_scope(client, cid) for signal in row["signals"]
                   if signal["riskType"] == "response_wait")
    assert waiting["signalActive"] is True
    with factory() as session:
        session.add(MessageRow(
            message_id="reply-wait-cleared", conversation_id=cid, sender_role=sender_role,
            body="亲，这单已经发出了。", applies_to_message_revision=4,
            client_message_key="reply-wait-cleared",
            created_at=customer_at + timedelta(seconds=140),
        ))
        session.flush()
        evaluate_risks(session, now=customer_at + timedelta(seconds=160))
        session.commit()
    cleared = next(signal for row in read_scope(client, cid) for signal in row["signals"]
                   if signal["riskType"] == "response_wait")
    assert cleared["riskStatus"] == "resolved"
    assert cleared["signalActive"] is False
    assert cleared["triggerSummary"] == "已回复，等待已结束"
    with factory() as session:
        session.add(MessageRow(
            message_id="customer-next-wait", conversation_id=cid, sender_role="customer",
            body="那赠品呢？", applies_to_message_revision=5,
            client_message_key="customer-next-wait",
            created_at=customer_at + timedelta(seconds=145),
        ))
        session.flush()
        evaluate_risks(session, now=customer_at + timedelta(seconds=270))
        session.commit()
    renewed = next(signal for row in read_scope(client, cid) for signal in row["signals"]
                   if signal["riskType"] == "response_wait")
    assert renewed["episode"] == 2
    assert renewed["signalActive"] is True
    assert renewed["riskStatus"] == "pending"
    assert not provider.calls
