import json

from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures
from tests.integration import test_risk_lifecycle as lifecycle

from app.domain.case_state.models import ConversationRow
from app.domain.consumer_service.models import (
    AutoReplyJobRow,
    RiskLifecycleRow,
    ServiceRiskAlertRow,
)

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def intervene(client, record, cid, headers=SUPPORT):
    return client.post(
        f"/api/support/desk/risks/{record['incidentId']}/intervene",
        headers=headers,
        json={"conversationId": cid, "expectedVersion": record["version"]},
    )


def test_takeover_changes_mode_cancels_ai_and_records_actual_actor(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "我想核对一下", key="baseline")
    fixtures._send(client, cid, "再不处理就投诉", key="risk")
    record = lifecycle.incident(client, cid)
    assert record["primaryConversationId"] == cid
    response = intervene(client, record, cid, {**SUPPORT, "X-Demo-Operator": "G002"})
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["incident"]["riskStatus"] == "in_progress"
    assert detail["handlingHistory"][0]["actor"] == "G002"
    assert detail["handlingHistory"][0]["note"] == f"接管会话 {cid}"
    with factory() as session:
        assert session.get(ConversationRow, cid).service_mode == "operator_assisted"
        jobs = list(session.scalars(select(AutoReplyJobRow).where(
            AutoReplyJobRow.conversation_id == cid,
        )))
        assert {job.status for job in jobs} == {"superseded", "cancelled"}
        assert not any(job.status in {"queued", "running"} for job in jobs)
    repeated = intervene(client, detail["incident"], cid)
    assert repeated.status_code == 200
    assert repeated.json()["handlingHistory"] == detail["handlingHistory"]
    assert not provider.calls


def test_merged_order_opens_latest_actionable_chat_and_takeover_does_not_handle_other_chats(workspace):
    client, factory, provider = workspace
    conversations = [fixtures._create(client), fixtures._create(client)]
    for index, cid in enumerate(conversations):
        fixtures._send(client, cid, "核对一下", key=f"baseline-{index}")
        fixtures._send(client, cid, "我要投诉", key=f"risk-{index}")
    with factory() as session:
        for row in session.scalars(select(ServiceRiskAlertRow).where(
            ServiceRiskAlertRow.conversation_id.in_(conversations),
        )):
            row.order_id = "fixture-shared-order"
            metadata = session.get(RiskLifecycleRow, row.alert_id)
            metadata.order_ids_json = json.dumps(["fixture-shared-order"])
        session.commit()
    record = lifecycle.incident(client, conversations[0])
    assert record["primaryConversationId"] == conversations[-1]
    response = intervene(client, record, conversations[-1])
    assert response.status_code == 200, response.text
    detail = response.json()
    assert all(
        signal["riskStatus"] == ("in_progress" if signal["conversationId"] == conversations[-1] else "pending")
        for signal in detail["incident"]["signals"]
    )
    with factory() as session:
        assert session.get(ConversationRow, conversations[0]).service_mode == "autonomous"
        assert session.get(ConversationRow, conversations[-1]).service_mode == "operator_assisted"
    assert not provider.calls


def test_old_version_other_conversation_and_customer_cannot_takeover(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "先核对", key="baseline")
    fixtures._send(client, cid, "我要投诉", key="risk")
    record = lifecycle.incident(client, cid)
    assert intervene(client, record, cid, CUSTOMER).status_code == 403
    other = fixtures._create(client)
    assert intervene(client, record, other).status_code == 422
    fixtures._send(client, cid, "我还要举报", key="new")
    assert intervene(client, record, cid).status_code == 409
    with factory() as session:
        assert session.get(ConversationRow, cid).service_mode == "autonomous"
    assert not provider.calls
