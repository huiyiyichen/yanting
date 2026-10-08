import json

import pytest
from sqlalchemy import select
from tests.integration import test_grounded_workflow as grounded
from tests.integration import test_reception_workspace as fixtures
from tests.integration import test_risk_lifecycle as lifecycle

from app.domain.consumer_service.auto_reception import process_job
from app.domain.consumer_service.models import (
    AssistantRunRow,
    AutoReplyJobRow,
    ServiceBreakpointAssessmentRow,
    SourceRecordRow,
)
from app.domain.consumer_service.risk_rules import evaluate_risks

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def repeated_draft(payload):
    result = json.loads(fixtures.OUTPUT)
    customers = [s for s in payload["sourceCatalog"] if s["kind"] == "customer_message"
                 and s["subjectId"] == payload["conversationId"]]
    result["reply_suggestions"][0]["body"] = "我先核对这次物流诉求的具体进展。"
    result["service_breakpoints"] = [{
        "kind": "repeated_question", "topic": "物流未更新", "reason": "同一物流诉求反复提出，需核对实际进展",
        "evidence": [{"source_ref": s["sourceId"], "quote": s["text"]} for s in customers[-2:]],
    }]
    return result


def setup_repeated(client):
    cid = lifecycle.create_manual(client)
    fixtures._send(client, cid, "请问物流有没有进展", key="first")
    fixtures._send(client, cid, "物流还是没有更新，帮我核对一下", key="second")
    return cid


def analyze(client, cid):
    return client.post(f"/api/support/desk/breakpoints/{cid}", headers=SUPPORT)


def test_verified_analysis_is_durable_and_reads_or_scans_do_not_call_the_model(workspace):
    client, factory, provider = workspace
    cid = setup_repeated(client)
    with factory() as session:
        source_before = {r.record_id: r.row_sha256 for r in session.scalars(select(SourceRecordRow))}
    grounded.make_provider(provider, repeated_draft)
    response = analyze(client, cid)
    assert response.status_code == 200, response.text
    assessment = response.json()
    assert assessment["analyzed"] and not assessment["stale"]
    assert assessment["findings"][0]["kind"] == "repeated_question"
    assert assessment["modelUsage"]["calls"] == 2 and assessment["isMock"]
    record = lifecycle.incident(client, cid)
    assert any(s["riskType"] == "service_breakpoint" for s in record["signals"])
    detail = client.get(f"/api/support/desk/risks/{record['incidentId']}", headers=SUPPORT).json()
    assert detail["serviceBreakpointAssessments"][0]["assessmentId"] == assessment["assessmentId"]
    assert any(e["body"] == "物流还是没有更新，帮我核对一下" for e in detail["evidence"])
    client.get(f"/api/support/desk/breakpoints/{cid}", headers=SUPPORT)
    client.post("/api/support/desk/risks/scan", headers=SUPPORT)
    assert len(provider.calls) == 2
    with factory() as session:
        assert {r.record_id: r.row_sha256 for r in session.scalars(select(SourceRecordRow))} == source_before


def test_new_information_marks_analysis_stale_without_clearing_or_closing_the_risk(workspace):
    client, _, provider = workspace
    cid = setup_repeated(client)
    grounded.make_provider(provider, repeated_draft)
    assert analyze(client, cid).status_code == 200
    before = lifecycle.incident(client, cid)
    fixtures._send(client, cid, "补充一下，物流仍然没有变化", key="third")
    current = lifecycle.incident(client, cid)
    assert current["version"] != before["version"]
    assert current["riskStatus"] == "pending" and current["signalActive"] is False
    assert current["currentAction"] == "review"
    assert current["needsReview"] is True
    assert client.get(f"/api/support/desk/breakpoints/{cid}", headers=SUPPORT).json()["stale"]
    assert lifecycle.action(client, before, "in_progress").status_code == 409
    assert len(provider.calls) == 2


def test_fresh_verified_empty_findings_request_review_but_do_not_close_the_risk(workspace):
    client, _, provider = workspace
    cid = setup_repeated(client)
    grounded.make_provider(provider, repeated_draft)
    assert analyze(client, cid).status_code == 200
    fixtures._send(client, cid, "已经收到，谢谢帮忙", key="resolved-customer")

    def resolved(payload):
        value = json.loads(fixtures.OUTPUT)
        value["service_breakpoints"] = []
        return value

    grounded.make_provider(provider, resolved)
    assert analyze(client, cid).status_code == 200
    current = lifecycle.incident(client, cid)
    assert current["riskStatus"] == "pending"
    assert current["signalActive"] is False and current["needsReview"]


def test_closed_risk_waits_for_new_verified_evidence_before_recurrence(workspace):
    client, factory, provider = workspace
    cid = setup_repeated(client)
    grounded.make_provider(provider, repeated_draft)
    assert analyze(client, cid).status_code == 200
    response = lifecycle.action(client, lifecycle.incident(client, cid), "in_progress")
    response = lifecycle.action(client, response.json()["incident"], "resolved", "人工复核第一轮")
    assert response.status_code == 200
    fixtures._send(client, cid, "物流又没有更新，仍请继续核对", key="recurrence")
    assert lifecycle.incident(client, cid)["riskStatus"] == "resolved"
    assert analyze(client, cid).status_code == 200
    record = lifecycle.incident(client, cid)
    assert record["riskStatus"] == "pending" and record["recurrenceCount"] == 1
    with factory() as session:
        evaluate_risks(session)
        session.commit()
    assert lifecycle.incident(client, cid)["recurrenceCount"] == 1


def test_missing_or_fabricated_analysis_does_not_overwrite_previous_findings_and_keeps_failure_cost(workspace):
    client, factory, provider = workspace
    cid = setup_repeated(client)
    grounded.make_provider(provider, repeated_draft)
    assert analyze(client, cid).status_code == 200
    with factory() as session:
        before = session.get(ServiceBreakpointAssessmentRow, cid).findings_json
    grounded.make_provider(provider, lambda _: json.loads(fixtures.OUTPUT))
    response = analyze(client, cid)
    assert response.status_code == 400
    with factory() as session:
        assert session.get(ServiceBreakpointAssessmentRow, cid).findings_json == before
        failed = session.scalar(select(AssistantRunRow).where(
            AssistantRunRow.conversation_id == cid, AssistantRunRow.status == "failed",
        ))
        assert failed is not None and json.loads(failed.usage_json)["calls"] == 2


def test_independent_semantic_review_rejects_different_topics_and_repairs_to_no_findings(workspace):
    client, _, provider = workspace
    cid = lifecycle.create_manual(client)
    fixtures._send(client, cid, "请查一下物流", key="logistics")
    fixtures._send(client, cid, "这款商品有什么价格信息", key="price")

    def draft(payload):
        value = repeated_draft(payload)
        if payload["repairIssues"]:
            value["service_breakpoints"] = []
        return value

    def verify(payload):
        wrong = bool(payload["draft"]["service_breakpoints"])
        return {"supported": not wrong, "issues": ["两个消费者消息是不同诉求"] if wrong else []}

    grounded.make_provider(provider, draft, verify)
    response = analyze(client, cid)
    assert response.status_code == 200, response.text
    assert not response.json()["findings"]
    assert response.json()["modelUsage"]["calls"] == 3
    assert not any(cid in r["conversationIds"] for r in client.get("/api/support/desk/risks", headers=SUPPORT).json())


def test_explicit_empty_result_is_saved_without_asking_verifier_to_invent_a_finding(workspace):
    client, _, provider = workspace
    cid = lifecycle.create_manual(client)
    fixtures._send(client, cid, "我想核对一次物流", key="single-question")
    grounded.make_provider(provider, lambda _: {"service_breakpoints": []},
                           lambda _: {"supported": False, "issues": ["没有候选"]})
    response = analyze(client, cid)
    assert response.status_code == 200, response.text
    assert response.json()["analyzed"] and not response.json()["stale"]
    assert response.json()["findings"] == []
    assert response.json()["modelUsage"]["calls"] == 1
    assert len(provider.calls) == 1


def test_unsupported_verdict_without_issues_cannot_publish_a_positive_finding(workspace):
    client, _, provider = workspace
    cid = setup_repeated(client)
    grounded.make_provider(provider, repeated_draft, lambda _: {"supported": False, "issues": []})
    assert analyze(client, cid).status_code == 400
    assert not client.get(f"/api/support/desk/breakpoints/{cid}", headers=SUPPORT).json()["analyzed"]


def test_automatic_reception_qualifies_findings_without_an_extra_model_request(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "请问物流有没有进展", key="first")
    fixtures._send(client, cid, "物流还是没有更新，帮我核对一下", key="second")
    grounded.make_provider(provider, repeated_draft)
    with factory() as session:
        job = session.scalar(select(AutoReplyJobRow).where(
            AutoReplyJobRow.conversation_id == cid, AutoReplyJobRow.status == "queued",
        ))
        job_id = job.job_id
    process_job(client.app.state.runtime, job_id)
    assert len(provider.calls) == 2
    assessment = client.get(f"/api/support/desk/breakpoints/{cid}", headers=SUPPORT).json()
    assert assessment["findings"] and not assessment["stale"]
    assert lifecycle.incident(client, cid)["riskStatus"] == "pending"


def test_automatic_reception_does_not_handoff_when_optional_breakpoint_proposal_is_unqualified(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "订单物流现在是什么状态？", key="customer")

    def draft(payload):
        value = json.loads(fixtures.OUTPUT)
        value["service_breakpoints"] = [{
            "kind": "repeated_question",
            "topic": "物流",
            "reason": "引用不存在的来源，必须放弃这条可选断点",
            "evidence": [
                {"source_ref": "fabricated-source", "quote": "虚构的消费者原文"},
                {"source_ref": "also-fabricated", "quote": "另一条虚构原文"},
            ],
        }]
        return value

    grounded.make_provider(provider, draft)
    with factory() as session:
        job = session.scalar(select(AutoReplyJobRow).where(
            AutoReplyJobRow.conversation_id == cid, AutoReplyJobRow.status == "queued",
        ))
        job_id = job.job_id
    process_job(client.app.state.runtime, job_id)
    with factory() as session:
        saved_job = session.get(AutoReplyJobRow, job_id)
        assert saved_job.status == "sent"
    messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert any(message["senderRole"] == "assistant" for message in messages)
    assert not any(message["body"] == "已转人工，客服将继续跟进。" for message in messages)
    assert len(provider.calls) == 2


@pytest.mark.parametrize("method", ["get", "post"])
def test_customer_cannot_read_or_trigger_internal_analysis(workspace, method):
    client, _, provider = workspace
    cid = fixtures._create(client)
    response = getattr(client, method)(f"/api/support/desk/breakpoints/{cid}", headers=CUSTOMER)
    assert response.status_code == 403
    assert not provider.calls
