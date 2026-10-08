"""Explicit mock workflow tests, not model advice-quality measurements."""

import json

import pytest
from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures
from tests.integration.test_grounded_workflow import make_provider

from app.domain.consumer_service.assistant import ConsumerServiceAssistant
from app.domain.consumer_service.auto_reception import process_job
from app.domain.consumer_service.models import AutoReplyJobRow

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER
KNOWLEDGE = [{
    "chunk_id": "routine@1#001", "document_id": "routine", "document_title": "分区护理",
    "document_version": "1",
    "quoted_excerpt": "非具体商品依据：油性区域温和清洁，干燥区域注意保湿；核对oil-free标签。",
}]


def advice(customer_ref, customer_quote, action="油性区域避免过度清洁。"):
    return {
        "category": "routine", "title": "按当前困扰选择",
        "action": action, "rationale": "根据你本轮描述的困扰选择通用护理方向。",
        "evidence": [
            {"source_ref": customer_ref, "quote": customer_quote},
            {"source_ref": "knowledge:routine@1#001", "quote": "油性区域温和清洁"},
        ],
        "claims": [],
    }


def install_knowledge(monkeypatch):
    monkeypatch.setattr(
        ConsumerServiceAssistant, "_knowledge", lambda self, query: (KNOWLEDGE, "available"),
    )


def test_advice_is_verified_sent_persisted_and_never_leaks_to_customer(workspace, monkeypatch):
    install_knowledge(monkeypatch)
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "T区出油，不要推荐品牌。")

    def draft(payload):
        customer = next(s for s in payload["sourceCatalog"] if s["kind"] == "customer_message")
        result = json.loads(fixtures.OUTPUT)
        result.update(intent="product_question", missing_information=[], next_steps=[])
        result["reply_suggestions"][0]["body"] = "您更在意当前使用感受。油性区域避免过度清洁。不推品牌。"
        result["personalized_advice"] = [advice(customer["sourceId"], "T区出油")]
        return result

    def verifier(payload):
        item = payload["draft"]["personalized_advice"][0]
        assert item["action"] in payload["draft"]["reply_suggestions"][0]["body"]
        assert len(item["evidence"]) == 2
        return {"supported": True, "issues": []}

    make_provider(provider, draft, verifier)
    with factory() as session:
        job_id = session.scalar(select(AutoReplyJobRow.job_id).where(
            AutoReplyJobRow.conversation_id == cid,
        ))
    process_job(client.app.state.runtime, job_id)
    path = f"/api/support/conversations/{cid}/assistant"
    cached = client.get(path, headers=SUPPORT).json()
    assert cached["verificationStatus"] == "verified" and cached["stale"] is False
    assert cached["modelUsage"]["calls"] == 2
    assert cached["personalizedAdvice"][0]["evidence"][1]["label"] == "分区护理"
    assert client.get(path, headers=SUPPORT).json()["personalizedAdvice"] == cached["personalizedAdvice"]
    messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert messages[-1]["body"] == cached["replySuggestions"][0]["body"]
    assert all("personalizedAdvice" not in message and "groundingSources" not in message
               for message in messages)
    assert client.get(path, headers=CUSTOMER).status_code == 403
    assert len(provider.calls) == 2


@pytest.mark.parametrize("scenario", ["correction", "attempted", "declined"])
def test_rejection_repairs_the_plan_and_reply_together(workspace, monkeypatch, scenario):
    install_knowledge(monkeypatch)
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "T区出油，两颊偏干。", key="old")
    latest = {
        "correction": "更正，两颊不干了，现在只担心T区出油。",
        "attempted": "保湿已经试过，还是出油。请给其他通用选择维度。",
        "declined": "不要再让我清洁保湿，只核对通用选择条件，不推品牌。",
    }[scenario]
    fixtures._send(client, cid, latest, key="latest")
    drafts = 0

    def draft(payload):
        nonlocal drafts
        drafts += 1
        latest_source = next(s for s in payload["sourceCatalog"] if s["text"] == latest)
        result = json.loads(fixtures.OUTPUT)
        result.update(intent="product_question", missing_information=[], next_steps=[])
        action = (
            "两颊偏干，先清洁保湿。"
            if drafts == 1 else "选择时核对oil-free标签，不从名字推断商品适用性。"
        )
        result["personalized_advice"] = [advice(latest_source["sourceId"], latest, action)]
        result["reply_suggestions"][0]["body"] = action
        if drafts == 2:
            if scenario == "declined":
                assert any("消费者本轮明确不再要求" in issue for issue in payload["repairIssues"])
            else:
                assert payload["repairIssues"] == ["未尊重最新纠正、已尝试措施或当前偏好"]
        return result

    def verifier(payload):
        assert payload["latestCustomerMessage"] == latest
        bad = "先清洁保湿" in payload["draft"]["personalized_advice"][0]["action"]
        return {"supported": not bad, "issues": ["未尊重最新纠正、已尝试措施或当前偏好"] if bad else []}

    make_provider(provider, draft, verifier)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["personalizedAdvice"][0]["action"] == value["replySuggestions"][0]["body"]
    assert "先清洁保湿" not in value["replySuggestions"][0]["body"]
    assert drafts == 2 and value["modelUsage"]["calls"] == (3 if scenario == "declined" else 4)
    assert sum(step["name"] == "知识检索" for step in value["workflowSteps"]) == 1


def test_fabricated_plan_never_enters_cache_or_customer_delivery(workspace, monkeypatch):
    install_knowledge(monkeypatch)
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "T区出油。")
    before_ids = {
        message["messageId"] for message in client.get(
            f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER,
        ).json()
    }

    def draft(payload):
        result = json.loads(fixtures.OUTPUT)
        result["intent"] = "product_question"
        result["personalized_advice"] = [advice("missing", "我不存在的肤质自述")]
        return result

    make_provider(provider, draft)
    with factory() as session:
        job_id = session.scalar(select(AutoReplyJobRow.job_id).where(
            AutoReplyJobRow.conversation_id == cid,
        ))
    process_job(client.app.state.runtime, job_id)
    assert client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT).json() is None
    messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert not any(message["senderRole"] == "assistant" and message["messageId"] not in before_ids
                   for message in messages)
    with factory() as session:
        job = session.get(AutoReplyJobRow, job_id)
        assert job.status == "handoff"
    assert len(provider.calls) == 2


def test_segmented_advice_and_reply_use_the_same_checked_product_sources(workspace, monkeypatch):
    client, factory, provider = workspace
    knowledge = [{
        "chunk_id": "matte@1#001", "document_id": "matte", "document_title": "美国官网资料",
        "document_version": "1", "quoted_excerpt": "Pro-Matte 的美国版官网说明为半哑光。",
        "applicability": {"products": ["REF-US-PROMATTE"]},
        "document_metadata": {
            "scope": "product_specific", "product_sku": "REF-US-PROMATTE",
            "product_name": "Infallible Pro-Matte 粉底液", "product_aliases": ["Pro-Matte"],
            "market": "US", "provenance": "official_reference",
        },
    }]
    monkeypatch.setattr(ConsumerServiceAssistant, "_knowledge", lambda self, query: (knowledge, "available"))
    cid = fixtures._create(client)
    fixtures._send(client, cid, "我更在意半哑光，不要保证个人适用。")

    def draft(payload):
        customer = next(item for item in payload["sourceCatalog"] if item["kind"] == "customer_message")
        part = {"text": "按美国官网说明，Pro-Matte 为半哑光。", "source_refs": ["knowledge:matte@1#001"]}
        result = json.loads(fixtures.OUTPUT)
        result.update(intent="product_question", missing_information=[], next_steps=[])
        result["reply_suggestions"] = [{"style": "recommended", "segments": [
            part, {"text": "这只是候选，不保证个人适用。"},
        ]}]
        result["personalized_advice"] = [{
            "category": "product_selection", "title": "按妆效列候选",
            "scope": "product_specific", "product_sku": "REF-US-PROMATTE",
            "action_parts": [part],
            "rationale_parts": [{"text": "对应您在意半哑光的偏好。", "source_refs": [customer["sourceId"]]}],
            "evidence": [
                {"source_ref": customer["sourceId"], "quote": "我更在意半哑光"},
                {"source_ref": "knowledge:matte@1#001", "quote": "Pro-Matte 的美国版官网说明为半哑光。"},
            ],
        }]
        return result

    def verifier(payload):
        reply = payload["draft"]["reply_suggestions"][0]
        plan = payload["draft"]["personalized_advice"][0]
        assert "segments" not in reply and "action_parts" not in plan
        assert all(claim["text"] in reply["body"] for claim in reply["claims"])
        assert plan["claims"][0]["text"] == plan["action"]
        return {"supported": True, "issues": []}

    make_provider(provider, draft, verifier)
    with factory() as session:
        job_id = session.scalar(select(AutoReplyJobRow.job_id).where(
            AutoReplyJobRow.conversation_id == cid,
        ))
    process_job(client.app.state.runtime, job_id)
    result = client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT).json()
    assert result["personalizedAdvice"][0]["action"] in result["replySuggestions"][0]["body"]
    assert result["modelUsage"]["calls"] == 2 and result["verificationStatus"] == "verified"
    assert result["personalizedAdvice"][0]["claims"][0]["text"] == result["personalizedAdvice"][0]["action"]
    assert client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT).json()[
        "personalizedAdvice"
    ] == result["personalizedAdvice"]
    messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert messages[-1]["body"] == result["replySuggestions"][0]["body"]
