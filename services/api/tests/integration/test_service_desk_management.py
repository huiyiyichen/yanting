from dataclasses import replace

import pytest
from sqlalchemy import select
from tests.integration import test_reception_workspace as reception_fixture
from tests.integration.test_reception_workspace import CUSTOMER, SUPPORT, _create, _send

from app.domain.consumer_service.grounding import collect_sources, validate_claims
from app.domain.consumer_service.models import ServiceTicketDetailRow, SourceRecordRow
from app.domain.platform.settings import get_enabled_template
from app.integrations.embedding_provider import MockEmbeddingProvider
from app.knowledge.models import KnowledgeBaseRow
from app.schemas.grounding import GroundingClaim

workspace = reception_fixture.workspace

DETAILS = [
    {"kind": "reship_exchange", "resolution": "exchange", "reason": "泵头损坏", "quantity": 1},
    {"kind": "offline_payment", "paymentType": "price_adjustment", "requestedAmount": "20.50", "reason": "核对价保"},
    {"kind": "logistics", "issueType": "stalled", "reason": "消费者询问停滞轨迹", "trackingNo": "TRACK123"},
    {"kind": "adverse_reaction", "symptomDescription": "消费者自述红肿", "stoppedUse": "yes", "soughtMedicalCare": "unknown"},
    {"kind": "return_refund", "requestType": "refund_only", "returnReason": "包装破损", "parcelType": "original"},
]


@pytest.mark.parametrize("detail", DETAILS)
def test_typed_local_ticket_details_roundtrip_without_changing_official_facts(workspace, detail):
    client, factory, provider = workspace
    with factory() as session:
        before = {r.record_id: r.values_json for r in session.scalars(select(SourceRecordRow))}
    response = client.post("/api/support/desk/tickets", headers={**SUPPORT, "X-Demo-Operator": "G002"}, json={
        "title": "工单资料验证", "conversationId": "S00001", "workOrderType": detail["kind"],
        "assignee": "G002", "note": "记录消费者事项，未执行业务动作", "localDetail": detail,
    })
    assert response.status_code == 200, response.text
    created = response.json()
    path = f"/api/support/desk/tickets/{created['ticketId']}"
    stored = client.get(path, headers=SUPPORT).json()
    assert stored["localDetail"].items() >= detail.items()
    assert stored["detail"] == {} and stored["sourceRecordId"] is None
    assert stored["events"][0]["actor"] == "G002"
    with factory() as session:
        assert session.get(ServiceTicketDetailRow, stored["ticketId"])
        assert {r.record_id: r.values_json for r in session.scalars(select(SourceRecordRow))} == before
    assert client.get(path, headers=CUSTOMER).status_code == 403
    assert not provider.calls


@pytest.mark.parametrize("kind, detail", [
    ("logistics", DETAILS[0]),
    ("offline_payment", {**DETAILS[1], "requestedAmount": "-1"}),
    ("offline_payment", {**DETAILS[1], "requestedAmount": "1.001"}),
    ("reship_exchange", {**DETAILS[0], "quantity": 0}),
    ("logistics", {**DETAILS[2], "transferStatus": "已到账"}),
    ("adverse_reaction", {**DETAILS[3], "symptomDescription": "  "}),
    ("return_refund", {**DETAILS[4], "requestType": "approve_refund"}),
])
def test_invalid_or_mismatched_ticket_fields_are_rejected(workspace, kind, detail):
    client, factory, _ = workspace
    response = client.post("/api/support/desk/tickets", headers=SUPPORT, json={
        "title": "无效资料验证", "conversationId": "S00001", "workOrderType": kind,
        "note": "仅本地验证", "localDetail": detail,
    })
    assert response.status_code == 422, response.text
    with factory() as session:
        assert not list(session.scalars(select(ServiceTicketDetailRow)))


def test_source_overlay_retains_original_details_and_rejects_stale_edits(workspace):
    client, factory, _ = workspace
    source = next(t for t in client.get("/api/support/desk/tickets", headers=SUPPORT).json()
                  if t["workOrderType"] == "reship_exchange" and t["status"] == "pending")
    path = f"/api/support/desk/tickets/{source['ticketId']}"
    payload = {
        "expectedRevision": 0, "status": "in_progress", "priority": "high", "assignee": "G003",
        "note": "人工补充处理诉求", "localDetail": DETAILS[0],
    }
    response = client.put(path, headers={**SUPPORT, "X-Demo-Operator": "G003"}, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["detail"] == source["detail"]
    assert response.json()["localDetail"]["reason"] == "泵头损坏"
    assert response.json()["events"][0]["actor"] == "G003"
    payload["localDetail"] = {**DETAILS[0], "reason": "过期改动"}
    assert client.put(path, headers=SUPPORT, json=payload).status_code == 409
    payload.update(expectedRevision=1, note="只更新跟进，不删除已录资料")
    payload.pop("localDetail")
    assert client.put(path, headers=SUPPORT, json=payload).json()["localDetail"]["reason"] == "泵头损坏"
    with factory() as session:
        sources = collect_sources(session, source["conversationId"])
        local = next(s for s in sources if s.source_id == f"followup:{source['ticketId']}")
        assert "人工录入" in local.text and "泵头损坏" in local.text


def test_operator_header_is_validated_and_risk_handling_keeps_real_demo_actor(workspace):
    client, _, _ = workspace
    roster = client.get("/api/support/desk/operators", headers=SUPPORT).json()
    assert roster["defaultOperatorId"] == "G001"
    assert {r["operatorId"] for r in roster["operators"]} == {"G001", "G002", "G003"}
    assert client.get("/api/support/desk/operators", headers=CUSTOMER).status_code == 403
    body = {"title": "身份验证", "conversationId": "S00001", "workOrderType": "logistics", "note": "仅本地"}
    assert client.post("/api/support/desk/tickets", headers={**SUPPORT, "X-Demo-Operator": "other"}, json=body).status_code == 422
    assert client.post("/api/support/desk/tickets", headers={**CUSTOMER, "X-Demo-Operator": "G003"}, json=body).status_code == 403
    incident = next(r for r in client.get("/api/support/desk/risks", headers=SUPPORT).json()
                    if r["riskStatus"] == "pending")
    response = client.post(f"/api/support/desk/risks/{incident['incidentId']}/status",
                           headers={**SUPPORT, "X-Demo-Operator": "G002"}, json={
        "status": "in_progress", "note": "模拟客服复核", "expectedVersion": incident["version"],
    })
    assert response.status_code == 200, response.text
    assert response.json()["handlingHistory"][0]["actor"] == "G002"
    assert all(s["handledBy"] == "G002" for s in response.json()["incident"]["signals"]
               if s["riskStatus"] == "in_progress")


def test_local_payment_requests_are_not_proof_of_executed_refunds(workspace):
    client, factory, _ = workspace
    order_id = client.get("/api/support/conversations/S00001/service-context", headers=SUPPORT).json()["orders"][0]["orderId"]
    for payment_type in ("price_adjustment", "price_adjustment", "refund", "refund"):
        response = client.post("/api/support/desk/tickets", headers=SUPPORT, json={
            "title": "本地申请验证", "conversationId": "S00001", "orderId": order_id,
            "workOrderType": "offline_payment", "note": "申请待核对，未实际退款",
            "localDetail": {**DETAILS[1], "paymentType": payment_type},
        })
        assert response.status_code == 200, response.text
        alerts = client.get("/api/support/risk-alerts", headers=SUPPORT).json()
        repeated = [r for r in alerts if r["conversationId"] == "S00001" and r["riskType"] == "repeated_refund"]
        if payment_type == "price_adjustment":
            assert not repeated
    assert repeated
    with factory() as session:
        sources = collect_sources(session, "S00001")
        local = next(s for s in sources if '"paymentType": "refund"' in s.text)
        body = "已经退款20.50元。"
        assert validate_claims(body, [GroundingClaim(text=body, source_refs=[local.source_id])],
                               {s.source_id: s for s in sources})


def test_ticket_workflow_preserves_source_and_risk(workspace):
    client, factory, _ = workspace
    rows = client.get("/api/support/desk/tickets", headers=SUPPORT).json()
    assert len(rows) == 80
    ticket = next(row for row in rows if row["status"] == "pending")
    with factory() as session:
        source = [(r.record_id, r.values_json) for r in session.scalars(select(SourceRecordRow))]
    risk_before = client.get("/api/support/risk-alerts", headers=SUPPORT).json()
    payload = {
        "expectedRevision": 0, "status": "resolved", "priority": "high",
        "assignee": "当前客服", "note": "已联系仓库核对", "dueAt": None,
    }
    path = f"/api/support/desk/tickets/{ticket['ticketId']}"
    assert client.put(path, headers=SUPPORT, json=payload).status_code == 422
    payload["status"] = "in_progress"
    response = client.put(path, headers=SUPPORT, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["events"][0]["note"] == payload["note"]
    assert client.put(path, headers=SUPPORT, json=payload).status_code == 409
    payload.update(expectedRevision=1, status="resolved", note="人工核对完成")
    assert client.put(path, headers=SUPPORT, json=payload).status_code == 200
    risk_after = client.get("/api/support/risk-alerts", headers=SUPPORT).json()
    assert {r["alertId"]: r["riskStatus"] for r in risk_after} == {
        r["alertId"]: r["riskStatus"] for r in risk_before
    }
    with factory() as session:
        assert [(r.record_id, r.values_json) for r in session.scalars(select(SourceRecordRow))] == source
    assert client.get(path, headers=CUSTOMER).status_code == 403


def test_local_ticket_is_linked_and_not_a_source_record(workspace):
    client, _, provider = workspace
    cid = _create(client)
    _send(client, cid)
    body = {
        "title": "物流跟进", "conversationId": cid, "workOrderType": "logistics",
        "note": "联系仓库核对", "assignee": "当前客服",
    }
    invalid = client.post("/api/support/desk/tickets", json={**body, "orderId": "unknown"}, headers=SUPPORT)
    assert invalid.status_code == 422
    response = client.post("/api/support/desk/tickets", json=body, headers=SUPPORT)
    assert response.status_code == 200, response.text
    ticket = response.json()
    assert ticket["sourceRecordId"] is None and ticket["ticketId"].startswith("LOCAL-")
    related = client.get(f"/api/support/desk/tickets?conversation_id={cid}", headers=SUPPORT).json()
    assert [r["ticketId"] for r in related] == [ticket["ticketId"]]
    assert not provider.calls


def test_incident_details_and_independent_handling(workspace):
    client, _, provider = workspace
    response = client.get("/api/support/desk/risks", headers=SUPPORT)
    assert response.status_code == 200, response.text
    incident = next(r for r in response.json() if r["riskStatus"] == "pending")
    path = f"/api/support/desk/risks/{incident['incidentId']}"
    detail = client.get(path, headers=SUPPORT).json()
    assert detail["contexts"] and detail["incident"]["signals"]
    version = detail["incident"]["version"]
    assert client.post(path + "/status", headers=SUPPORT, json={"status": "resolved", "note": "核实", "expectedVersion": version}).status_code == 422
    assert client.post(path + "/status", headers=SUPPORT, json={"status": "in_progress", "note": "   ", "expectedVersion": version}).status_code == 422
    for status in ("in_progress", "resolved"):
        response = client.post(path + "/status", headers=SUPPORT, json={"status": status, "note": "人工核实", "expectedVersion": version})
        assert response.status_code == 200, response.text
        version = response.json()["incident"]["version"]
    result = client.get(path, headers=SUPPORT).json()
    assert result["incident"]["riskStatus"] == "resolved"
    assert len(result["handlingHistory"]) == 2
    scan = client.post("/api/support/desk/risks/scan", headers=SUPPORT)
    assert scan.status_code == 200, scan.text
    assert scan.json()["referenceTime"]
    assert not provider.calls


def test_prompt_custom_binding_versions_and_actual_use(workspace):
    client, factory, provider = workspace
    response = client.post("/api/platform/prompt-templates", headers=SUPPORT, json={
        "code": "EMPATHY_V2", "name": "共情接待", "content": "先读取已知事实 CUSTOM-BOUND",
    })
    assert response.status_code == 200, response.text
    template_id = response.json()["templateId"]
    listed = client.get("/api/platform/prompt-templates", headers=SUPPORT).json()
    assert any(r["templateId"] == template_id for r in listed)
    path = f"/api/platform/prompt-templates/{template_id}"
    assert client.post(path + "/binding", headers=SUPPORT, json={"purpose": "LOREAL_ASSISTANT"}).status_code == 200
    client.get("/api/platform/prompt-templates", headers=SUPPORT)
    with factory() as session:
        assert get_enabled_template(session, "LOREAL_ASSISTANT").template_id == template_id
    cid = _create(client)
    _send(client, cid)
    assert client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT).status_code == 200
    assert any("CUSTOM-BOUND" in messages[0].content for messages in provider.calls)
    updated = client.put(path, headers=SUPPORT, json={"expectedRevision": 1, "content": "新版共情"})
    assert updated.status_code == 200
    versions = client.get(path + "/revisions", headers=SUPPORT).json()
    assert {r["revision"] for r in versions} == {1, 2}
    assert client.post(path + "/restore", headers=SUPPORT, json={"revision": 1, "expectedRevision": 2}).json()["revision"] == 3
    assert client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT).json()["stale"]


def test_knowledge_draft_preview_and_failed_publication(workspace, tmp_path):
    client, factory, _ = workspace
    client.app.state.runtime.settings.runtime_dir = str(tmp_path / "runtime")
    with factory() as session:
        session.add(KnowledgeBaseRow(knowledge_base_id="loreal-service", name="服务知识", source_type="sop"))
        session.commit()
    response = client.post("/api/platform/knowledge/documents", headers=SUPPORT, json={
        "knowledgeBaseId": "loreal-service", "title": "物流处理", "content": "# 物流\n\n核对订单和物流记录，不承诺到账。"
    })
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["chunks"] and document["status"] == "draft"
    path = f"/api/platform/knowledge/documents/{document['documentId']}"
    assert client.get(path, headers=SUPPORT).json()["content"].startswith("# 物流")
    assert client.get(path, headers=CUSTOMER).status_code == 403
    publish = client.post("/api/platform/knowledge/publish", headers=SUPPORT)
    assert publish.status_code == 200, publish.text
    assert publish.json()["ok"] is False
    assert client.get(path, headers=SUPPORT).json()["status"] == "failed"


def test_knowledge_publish_version_and_failed_rebuild_preserve_snapshot(workspace, tmp_path):
    # A deterministic index fixture exercises publication, not model quality or live readiness.
    class IndexFixture(MockEmbeddingProvider):
        def encode(self, texts, *, is_query=False):
            return replace(super().encode(texts, is_query=is_query), is_mock=False)

    client, factory, _ = workspace
    runtime = client.app.state.runtime
    runtime.settings.runtime_dir = str(tmp_path / "runtime")
    runtime.settings.qdrant_path = str(tmp_path / "qdrant")
    runtime.embedding_provider = IndexFixture(reason="index lifecycle fixture", model_id="fixture-not-live")
    with factory() as session:
        session.add(KnowledgeBaseRow(knowledge_base_id="loreal-service", name="服务知识", source_type="sop"))
        session.commit()
    body = {"title": "服务规则", "content": "# 物流\n\n核对当前订单物流，不承诺时限。"}
    created = client.post("/api/platform/knowledge/documents", headers=SUPPORT, json=body).json()
    path = f"/api/platform/knowledge/documents/{created['documentId']}"
    first = client.post("/api/platform/knowledge/publish", headers=SUPPORT).json()
    assert first["ok"], first
    assert client.get(path, headers=SUPPORT).json()["status"] == "published"
    body.update(expectedRevision=1, content="# 物流\n\n新版规则：先读取订单，再核对物流。")
    assert client.put(path, headers=SUPPORT, json=body).status_code == 200
    second = client.post("/api/platform/knowledge/publish", headers=SUPPORT).json()
    assert second["ok"] and second["snapshotId"] != first["snapshotId"], second
    body.update(expectedRevision=2, content="# 物流\n\n待发布的第三版。")
    assert client.put(path, headers=SUPPORT, json=body).status_code == 200
    runtime.embedding_provider = MockEmbeddingProvider(reason="simulate unavailable publication")
    failure = client.post("/api/platform/knowledge/publish", headers=SUPPORT).json()
    assert failure["ok"] is False
    overview = client.get("/api/platform/knowledge", headers=SUPPORT).json()
    assert overview["snapshotId"] == second["snapshotId"]
