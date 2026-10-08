import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures

from app.domain.consumer_service.grounding import collect_sources
from app.domain.consumer_service.models import AssistantRunRow
from app.errors import ProviderTimeout
from app.integrations.model_provider import ChatResult

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def make_provider(provider, draft_builder, verifier=None):
    def complete(messages, **kwargs):
        provider._calls.append(list(messages))
        payload = json.loads(messages[1].content)
        if messages[0].content.startswith("GROUNDING_REVIEW_V1"):
            result = verifier(payload) if verifier else {"supported": True, "issues": []}
        else:
            result = draft_builder(payload)
        return ChatResult(text=json.dumps(result, ensure_ascii=False), model="grounding-fixture",
                          latency_seconds=0.01, is_mock=True, prompt_tokens=80, completion_tokens=30)
    provider.complete = complete


@pytest.mark.parametrize("automatic", [False, True])
def test_customer_language_policy_applies_after_saved_prompts_in_both_modes(workspace, automatic):
    from app.domain.consumer_service.grounded_workflow import run_grounded_workflow
    from app.domain.platform.settings import get_enabled_template

    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "你好，这笔退款有进展了吗？")
    purpose = "LOREAL_AUTO_REPLY" if automatic else "LOREAL_ASSISTANT"
    with factory() as session:
        template = get_enabled_template(session, purpose)
        template.content = "SAVED-CUSTOM-PROMPT"
        session.commit()
    make_provider(provider, lambda _: json.loads(fixtures.OUTPUT))
    with factory() as session:
        result = run_grounded_workflow(
            session, provider, cid, automatic=automatic, knowledge_search=lambda _: ([], "not_found"),
        )
        assert get_enabled_template(session, purpose).content == "SAVED-CUSTOM-PROMPT"
    prompt = provider.calls[0][0].content
    assert prompt.index("SAVED-CUSTOM-PROMPT") < prompt.index("面向消费者的话术")
    assert "合计2–5句" in prompt
    assert "退款金额来自售后记录refundAmount" in prompt
    assert result["draft"] is not None
    assert len(provider.calls) == 2


@pytest.mark.parametrize("automatic", [False, True])
def test_optional_product_advice_is_independent_of_a_valid_customer_reply(workspace, automatic):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "亲，我想换个洁面，帮我选一款吧。")

    def draft(payload):
        customer = next(source for source in payload["sourceCatalog"]
                        if source["kind"] == "customer_message")
        value = json.loads(fixtures.OUTPUT)
        value.update(
            intent="product_question", current_question="客户希望选择一款洁面。",
            service_summary="客户准备换洁面，待了解洗后感受。", missing_information=["洗后感受"],
            next_steps=["了解洗后感受"],
            reply_suggestions=[{"style": "recommended", "segments": [{
                "text": "亲，平时洗完脸会紧绷，还是容易出油呀？", "source_refs": [],
            }]}],
            personalized_advice=[{
                "category": "product_selection", "title": "选择洁面",
                "action": "这款适合敏感肌。", "rationale": "客户希望选择洁面。",
                "scope": "general_consumer", "evidence": [
                    {"source_ref": customer["sourceId"], "quote": customer["text"]},
                    {"source_ref": "knowledge:unavailable", "quote": "商品资料"},
                ],
            }],
        )
        return value

    make_provider(provider, draft)
    if automatic:
        from app.domain.consumer_service.auto_reception import process_job
        from app.domain.consumer_service.models import AutoReplyJobRow

        with factory() as session:
            job = session.scalar(select(AutoReplyJobRow).where(AutoReplyJobRow.conversation_id == cid))
            job_id = job.job_id
        process_job(client.app.state.runtime, job_id)
        with factory() as session:
            assert session.get(AutoReplyJobRow, job_id).status == "sent"
        response = client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT)
    else:
        response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert response.json()["verificationStatus"] == "verified"
    assert response.json()["replySuggestions"][0]["body"] == "亲，平时洗完脸会紧绷，还是容易出油呀？"
    assert response.json()["personalizedAdvice"] == []
    assert len(provider.calls) == 2


def test_official_refund_amount_uses_business_record_not_staff_message(workspace):
    client, _, provider = workspace

    def draft(payload):
        assert payload["currentServiceContext"]["conversationId"] == "S00381"
        assert payload["currentServiceContext"]["orderIds"] == ["6920914776440905581"]
        source = next(source for source in payload["sourceCatalog"]
                      if source["kind"] == "work_order" and source["fields"].get("refundAmount") == 10)
        assert source["fields"]["conversationId"] == "S00381"
        value = json.loads(fixtures.OUTPUT)
        value.update(current_question="客户咨询退款并致谢。",
                     service_summary="客户此前反映退货后无法退款。客服曾告知走线下退款，客户已补充信息。")
        value["reply_suggestions"] = [{
            "style": "recommended",
            "segments": [{"text": "亲，这笔退款是10元，目前还在审核中。",
                          "source_refs": [source["sourceId"]]}],
        }]
        return value

    def verify(payload):
        assert payload["currentServiceContext"]["conversationId"] == "S00381"
        assert payload["currentServiceContext"]["orderIds"] == ["6920914776440905581"]
        assert any(source["fields"].get("conversationId") == "S00038"
                   for source in payload["sourceCatalog"] if source["kind"] == "order")
        return {"supported": True, "issues": []}

    make_provider(provider, draft, verify)
    response = client.post("/api/support/reception/S00381/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    reply = response.json()["replySuggestions"][0]
    assert reply["body"] == "亲，这笔退款是10元，目前还在审核中。"
    assert {item["key"] for item in reply["empathyDimensions"]} == {
        "emotion_response", "business_handling", "personalized",
    }


def test_reply_candidates_are_qualified_independently(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "亲，这个洁面的成分你帮我看看吧。")

    def draft(payload):
        value = json.loads(fixtures.OUTPUT)
        value["intent"] = "product_recommendation"
        value["reply_suggestions"] = [
            {"style": "recommended", "body": "亲，把包装上的成分表发我，我帮您一起看看哦。"},
            {"style": "concise", "body": "这款不含酒精。"},
        ]
        return value

    def verify(payload):
        assert [item["style"] for item in payload["draft"]["reply_suggestions"]] == ["recommended"]
        return {"supported": True, "issues": []}

    make_provider(provider, draft, verify)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert response.json()["replySuggestions"][0]["body"] == "亲，把包装上的成分表发我，我帮您一起看看哦。"
    assert response.json()["intent"] == "unknown"
    assert len(response.json()["replySuggestions"]) == 1
    assert len(provider.calls) == 2
    assert response.json()["modelUsage"]["calls"] == 2


def test_draft_repair_and_verification_share_one_remaining_budget(workspace, monkeypatch):
    from app.domain.consumer_service import grounded_workflow

    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(grounded_workflow, "monotonic", lambda: clock.now)
    budgets = []

    def complete(messages, **kwargs):
        provider._calls.append(list(messages))
        budgets.append(kwargs["timeout_seconds"])
        clock.now += 2
        if messages[0].content.startswith("GROUNDING_REVIEW_V1"):
            value = {"supported": True, "issues": []}
        else:
            value = json.loads(fixtures.OUTPUT)
            if len(budgets) == 1:
                value["memory"] = [{"category": "known", "source_ref": "missing", "quote": "bad"}]
        return ChatResult(text=json.dumps(value), model="timeout-fixture", latency_seconds=2,
                          is_mock=True, prompt_tokens=80, completion_tokens=30)

    provider.complete = complete
    with factory() as session:
        result = grounded_workflow.run_grounded_workflow(
            session, provider, cid, automatic=True, knowledge_search=lambda _: ([], "not_found"),
            timeout_seconds=10,
        )
    assert budgets == [10, 8, 6]
    assert len(result["calls"]) == 3
    assert any(step.status == "needs_repair" for step in result["steps"])


@pytest.mark.parametrize("slow_stage", ["retrieve", "draft", "verify"])
def test_exhausted_budget_stops_the_next_call_and_retains_completed_usage(workspace, monkeypatch, slow_stage):
    from app.domain.consumer_service import grounded_workflow

    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(grounded_workflow, "monotonic", lambda: clock.now)
    calls = []

    def search(_query):
        if slow_stage == "retrieve":
            clock.now += 11
        return [], "not_found"

    def complete(messages, **kwargs):
        stage = "verify" if messages[0].content.startswith("GROUNDING_REVIEW_V1") else "draft"
        calls.append(stage)
        assert kwargs["timeout_seconds"] > 0
        clock.now += 11 if slow_stage == stage else 2
        value = {"supported": True, "issues": []} if stage == "verify" else json.loads(fixtures.OUTPUT)
        return ChatResult(text=json.dumps(value), model="timeout-fixture", latency_seconds=2,
                          is_mock=True, prompt_tokens=80, completion_tokens=30)

    provider.complete = complete
    with factory() as session, pytest.raises(ProviderTimeout) as captured:
        grounded_workflow.run_grounded_workflow(
            session, provider, cid, automatic=True, knowledge_search=search,
            timeout_seconds=10,
        )
    expected_calls = 0 if slow_stage == "retrieve" else 1 if slow_stage == "draft" else 2
    assert len(calls) == expected_calls
    assert len(captured.value.workflow_calls) == expected_calls
    assert all(call["promptTokens"] == 80 for call in captured.value.workflow_calls)
    assert all(call["inputCharacters"] > 0 for call in captured.value.workflow_calls)
    assert captured.value.workflow_steps[-1]["status"] == "failed"


def test_memory_is_cited_persisted_and_becomes_stale_after_new_information(workspace, monkeypatch):
    from app.domain.consumer_service.assistant import ConsumerServiceAssistant

    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "我是干皮，泵头按了两次还没用。", key="facts")
    monkeypatch.setattr(ConsumerServiceAssistant, "_knowledge", lambda self, query: ([{
        "chunk_id": "general@1#001", "document_id": "general", "document_title": "通用资料",
        "document_version": "1", "quoted_excerpt": "商品适用性未提供，不作判断。",
    }], "available"))

    def draft(payload):
        assert any(s["kind"] == "knowledge" for s in payload["sourceCatalog"])
        assert not any(s["kind"] == "knowledge" for s in payload["memorySourceCatalog"])
        assert {s["sourceId"] for s in payload["memorySourceCatalog"]} == {
            s["sourceId"] for s in payload["sourceCatalog"] if s["kind"] != "knowledge"
        }
        assert all(set(s) == {"sourceId", "kind"} for s in payload["memorySourceCatalog"])
        source = next(s for s in payload["sourceCatalog"] if "我是干皮" in s["text"])
        result = json.loads(fixtures.OUTPUT)
        result["memory"] = [
            {"category": "known", "label": "肤质自述", "source_ref": source["sourceId"], "quote": "我是干皮"},
            {"category": "attempted", "label": "已尝试", "source_ref": source["sourceId"], "quote": "泵头按了两次还没用"},
        ]
        result["intent"] = "replacement"
        result["reply_suggestions"][0]["body"] = "您已经试过按压泵头，我先核对相关记录。"
        return result

    make_provider(provider, draft)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["verificationStatus"] == "verified"
    assert result["modelUsage"]["calls"] == 2
    assert result["modelUsage"]["promptTokens"] == 160
    assert result["modelUsage"]["inputCharacters"] == sum(
        len(message.content) for call in provider.calls for message in call
    )
    assert len(result["workflowSteps"]) == 6
    memory = client.get(f"/api/support/reception/{cid}/memory", headers=SUPPORT).json()
    assert memory["verified"] and not memory["stale"]
    assert {m["quote"] for m in memory["items"]} == {"我是干皮", "泵头按了两次还没用"}
    fixtures._send(client, cid, "更正一下，是混合偏干。", key="correction")
    assert client.get(f"/api/support/reception/{cid}/memory", headers=SUPPORT).json()["stale"]
    assert client.get(f"/api/support/reception/{cid}/memory", headers=CUSTOMER).status_code == 403


def test_compact_memory_index_retains_every_original_source_body(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    text = "我已经试过一次，仍担心后续处理。" * 50
    fixtures._send(client, cid, text)
    with factory() as session:
        expected = {source.source_id: source.dump() for source in collect_sources(session, cid)}

    def draft(payload):
        factual = {source["sourceId"]: source for source in payload["sourceCatalog"]
                   if source["kind"] != "knowledge"}
        assert factual == expected
        memory_ids = {source["sourceId"] for source in payload["memorySourceCatalog"]}
        assert memory_ids == set(expected)
        compact = json.dumps(payload["memorySourceCatalog"], ensure_ascii=False)
        legacy = json.dumps(list(expected.values()), ensure_ascii=False)
        assert len(compact) < len(legacy)
        assert text not in compact
        assert all(source["text"] in json.dumps(payload["sourceCatalog"], ensure_ascii=False)
                   for source in expected.values())
        return json.loads(fixtures.OUTPUT)

    make_provider(provider, draft)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert len(provider.calls) == 2


def test_draft_and_verifier_receive_full_retrieved_conditions_not_ui_excerpt(workspace, monkeypatch):
    from app.domain.consumer_service.assistant import ConsumerServiceAssistant

    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "只核对已知商品资料，不保证适用。")
    full_text = "品牌资料。" * 100 + "末尾条件：不保证个人适用，不能把水乳配方说明套到面霜。"
    short_text = full_text[:399] + "…"
    monkeypatch.setattr(ConsumerServiceAssistant, "_knowledge", lambda self, query: ([{
        "chunk_id": "cn@1#1", "document_id": "cn", "document_title": "中国商品资料",
        "document_version": "1", "quoted_excerpt": short_text, "source_text": full_text,
    }], "available"))

    def inspect_sources(payload):
        source = next(source for source in payload["sourceCatalog"] if source["kind"] == "knowledge")
        assert source["text"] == full_text

    def draft(payload):
        inspect_sources(payload)
        assert "不额外增加清洁、护理或再次试用建议" in provider.calls[-1][0].content
        value = json.loads(fixtures.OUTPUT)
        value["reply_suggestions"][0]["body"] = "我按本次已有资料核对，不作个人适用保证。"
        return value

    def verify(payload):
        inspect_sources(payload)
        assert "应删除与当前任务无关的话语" in provider.calls[-1][0].content
        return {"supported": True, "issues": []}

    make_provider(provider, draft, verify)
    from app.domain.consumer_service.auto_reception import process_job
    from app.domain.consumer_service.models import AutoReplyJobRow

    runtime = client.app.state.runtime
    with runtime.new_session() as session:
        job = session.scalar(select(AutoReplyJobRow).where(AutoReplyJobRow.conversation_id == cid))
        job_id = job.job_id
    process_job(runtime, job_id)
    response = client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value is not None
    assert value["groundingSources"][-1]["text"] == full_text
    assert value["knowledgeEvidence"][0]["quoted_excerpt"] == short_text
    assert "source_text" not in value["knowledgeEvidence"][0]
    assert len(provider.calls) == 2


def test_drafting_uses_json_and_explicit_advice_field_contract_without_extra_calls(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "按真实商品资料比较妆效，不保证个人适用。")
    formats = []

    def complete(messages, **kwargs):
        provider._calls.append(list(messages))
        formats.append(kwargs["json_mode"])
        payload = json.loads(messages[1].content)
        if messages[0].content.startswith("GROUNDING_REVIEW_V1"):
            value = {"supported": True, "issues": []}
        else:
            schema = payload["adviceContract"]
            assert schema["additionalProperties"] is False
            assert {"action_parts", "rationale_parts", "evidence"} <= set(schema["required"])
            assert "segments" in payload["replyContract"]["properties"]
            assert "程序拼成body/claims" in payload["claimFieldRules"]["reply_suggestions"]
            assert "action_parts/rationale_parts" in payload["claimFieldRules"]["personalized_advice"]
            value = json.loads(fixtures.OUTPUT)
        return ChatResult(
            text=json.dumps(value), model="explicit-contract-fixture",
            is_mock=True, latency_seconds=0, prompt_tokens=20, completion_tokens=10,
        )

    provider.complete = complete
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert formats == [True, True]
    assert response.json()["modelUsage"]["calls"] == 2


def test_contract_repair_retains_rejected_object_only_in_request_memory(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "按已知资料继续核对。")
    drafts = 0

    def draft(payload):
        nonlocal drafts
        drafts += 1
        result = json.loads(fixtures.OUTPUT)
        if drafts == 1:
            result["current_question"] = "REJECTED_ONLY_IN_MEMORY:" + "x" * 500
        else:
            assert payload["previousDraft"]["current_question"].startswith("REJECTED_ONLY_IN_MEMORY:")
            assert any("current_question:string_too_long" in issue for issue in payload["repairIssues"])
            assert any("max_length=500" in issue for issue in payload["repairIssues"])
        return result

    make_provider(provider, draft)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert response.json()["modelUsage"]["calls"] == 3
    assert "REJECTED_ONLY_IN_MEMORY:" not in response.text
    with factory() as session:
        run = session.scalar(select(AssistantRunRow).where(AssistantRunRow.conversation_id == cid))
        assert "REJECTED_ONLY_IN_MEMORY:" not in run.trace_json
        assert "REJECTED_ONLY_IN_MEMORY:" not in run.usage_json


def test_instructions_cover_attempts_and_known_information_in_both_draft_and_verifier(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "已经解锁并按压十次，还是没出液。")
    make_provider(provider, lambda _: json.loads(fixtures.OUTPUT))
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    draft_prompt, verifier_prompt = (messages[0].content for messages in provider.calls)
    assert "分别提取attempted和concern" in draft_prompt
    assert "missing_information和next_steps不能" in draft_prompt
    assert "应归attempted" in verifier_prompt
    assert "再次当缺项" in verifier_prompt
    assert "不据此说包裹已签收" in draft_prompt


def test_declined_operation_in_followup_fields_is_repaired_before_saving(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "已经解锁并按压十次，还是没出液。不要再折腾，只梳理还缺什么资料。")
    drafts = 0

    def draft(payload):
        nonlocal drafts
        drafts += 1
        result = json.loads(fixtures.OUTPUT)
        result["reply_suggestions"][0]["body"] = "我先核对已有记录，不要求您再操作。"
        result["missing_information"] = (
            ["是否已尝试清洁泵头出口", "订单号"] if drafts == 1 else ["订单号"]
        )
        result["next_steps"] = ["核对已有订单和售后记录"]
        if drafts == 2:
            assert any("missing_information" in issue and "只核对资料" in issue
                       for issue in payload["repairIssues"])
        return result

    make_provider(provider, draft)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["missingInformation"] == ["订单号"]
    assert result["modelUsage"]["calls"] == 3
    assert result["verificationStatus"] == "verified"
    assert drafts == 2


def test_staff_action_cannot_be_saved_as_a_consumer_attempt_even_with_an_exact_quote(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    client.post(f"/api/customer/conversations/{cid}/handoff", headers=CUSTOMER)
    client.post(f"/api/support/reception/{cid}/messages", headers=SUPPORT,
                json={"body": "已创建工单，后续需核对", "clientMessageKey": "staff"})
    fixtures._send(client, cid, "我已按压两次，仍不出液")
    drafts = 0

    def draft(payload):
        nonlocal drafts
        drafts += 1
        result = json.loads(fixtures.OUTPUT)
        if drafts == 1:
            source = next(s for s in payload["sourceCatalog"] if s["kind"] == "staff_message")
            result["memory"] = [{"category": "attempted", "source_ref": source["sourceId"],
                                 "quote": "已创建工单"}]
        else:
            assert any("消费者本人自述" in issue for issue in payload["repairIssues"])
            source = next(s for s in payload["sourceCatalog"] if s["kind"] == "customer_message")
            result["memory"] = [{"category": "attempted", "source_ref": source["sourceId"],
                                 "quote": "我已按压两次"}]
        return result

    make_provider(provider, draft)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    memory = response.json()["memoryItems"]
    assert len(memory) == 1 and memory[0]["quote"] == "我已按压两次"
    assert response.json()["modelUsage"]["calls"] == 3


def test_search_scope_and_customer_concern_rules_are_included_in_agent_context(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "我更在意粉底服帖，本次检索未找到对应资料。")
    make_provider(provider, lambda payload: (
        json.loads(fixtures.OUTPUT)
        | {"memory": [{"category": "concern", "source_ref": next(
            item["sourceId"] for item in payload["sourceCatalog"] if item["kind"] == "customer_message"
        ), "quote": "我更在意粉底服帖"}]}
    ))
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    system_prompt = provider.calls[0][0].content
    assert "knowledgeSearchIsExhaustive=false" in system_prompt
    assert "更在意/最关心/担心" in system_prompt


def test_unproven_whole_catalog_absence_is_repaired_to_a_scoped_search_result(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "有没有这个商品的现成资料，没找到就告诉我不能确认。")
    drafts = 0

    def draft(payload):
        nonlocal drafts
        drafts += 1
        result = json.loads(fixtures.OUTPUT)
        result["reply_suggestions"][0]["body"] = (
            "目录里没有这款商品记录。" if drafts == 1
            else "这款我这边暂时没查到相关资料，麻烦您发一下包装成分表哦。"
        )
        if drafts == 2:
            assert any("全目录盘点" in issue for issue in payload["repairIssues"])
            repair = json.loads(provider.calls[-1][-1].content.split("\n", 1)[1])
            assert any("knowledgeSearchIsExhaustive=false" in rule for rule in repair["rules"])
        return result

    make_provider(provider, draft)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    body = response.json()["replySuggestions"][0]["body"]
    assert "暂时没查到" in body and "检索" not in body
    assert response.json()["modelUsage"]["calls"] == 3


def test_off_contract_emotion_label_does_not_consume_the_repair(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "请问这款洁面孕妇能用吗？我怀孕三个月了。")
    make_provider(provider, lambda payload: json.loads(fixtures.OUTPUT) | {"emotion_level": "worried"})
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    assert response.json()["emotionLevel"] == "unknown"
    assert response.json()["modelUsage"]["calls"] == 2


def test_semantic_checker_can_reject_a_plausible_but_unsupported_statement_and_repair(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "查询物流")
    drafts = 0

    def draft(payload):
        nonlocal drafts
        drafts += 1
        assert payload["serviceCapabilities"]["queryExistingOrderAndTicketRecords"] is True
        assert payload["serviceCapabilities"]["queryRealTimeLogistics"] is False
        if drafts == 2:
            assert payload["previousDraft"]["reply_suggestions"][0]["body"] == "包裹正在派送。"
            assert payload["repairIssues"] == ["没有派送记录"]
        result = json.loads(fixtures.OUTPUT)
        result["reply_suggestions"][0]["body"] = (
            "包裹正在派送。" if drafts == 1 else "我先核对物流，方便提供订单号吗？"
        )
        return result

    def verify(payload):
        assert payload["serviceCapabilities"]["proactiveFollowUp"] is False
        assert payload["serviceCapabilities"]["executeAfterSalesActions"] is False
        unsupported = "正在派送" in payload["draft"]["reply_suggestions"][0]["body"]
        return {"supported": not unsupported, "issues": ["没有派送记录"] if unsupported else []}

    make_provider(provider, draft, verify)
    result = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert result.status_code == 200, result.text
    value = result.json()
    assert "正在派送" not in value["replySuggestions"][0]["body"]
    assert value["modelUsage"]["calls"] == 4
    assert sum(s["name"] == "服务轨迹" for s in value["workflowSteps"]) == 1
    assert sum(s["name"] == "知识检索" for s in value["workflowSteps"]) == 1
    repaired = [s for s in value["workflowSteps"] if s["status"] == "needs_repair"]
    assert repaired[0]["issues"] == ["没有派送记录"]
    assert value["workflowSteps"][-1]["issues"] == []
    with factory() as session:
        run = session.scalar(select(AssistantRunRow).where(AssistantRunRow.conversation_id == cid))
        assert json.loads(run.trace_json) == value["workflowSteps"]


def test_deterministic_repair_retains_bounded_issues_without_full_draft(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "查询物流")
    drafts = 0

    def draft(payload):
        nonlocal drafts
        drafts += 1
        result = json.loads(fixtures.OUTPUT)
        if drafts == 1:
            result["memory"] = [{"category": "known", "source_ref": "fabricated", "quote": "退款成功"}]
        else:
            assert payload["repairIssues"]
            assert len(provider.calls[-1]) == 3
            repair = json.loads(provider.calls[-1][-1].content.split("\n", 1)[1])
            assert repair["issues"] == payload["repairIssues"]
            assert repair["memorySourceIds"] == [source["sourceId"] for source in payload["memorySourceCatalog"]]
            assert repair["replySourceIds"] == [source["sourceId"] for source in payload["sourceCatalog"]]
        return result

    make_provider(provider, draft)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    repaired = [s for s in response.json()["workflowSteps"] if s["status"] == "needs_repair"]
    assert repaired and repaired[0]["issues"]
    assert len(repaired[0]["issues"]) <= 8
    assert all(len(issue) <= 200 for issue in repaired[0]["issues"])
    assert set(repaired[0]) == {"name", "status", "durationMs", "attempt", "issues"}


def test_claim_body_mismatch_is_repaired_before_independent_verification(workspace, monkeypatch):
    from app.domain.consumer_service.assistant import ConsumerServiceAssistant

    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "敏感肌适用性资料不足时不要猜。")
    monkeypatch.setattr(ConsumerServiceAssistant, "_knowledge", lambda self, query: ([{
        "chunk_id": "general@1#001", "document_id": "general", "document_title": "通用资料",
        "document_version": "1", "quoted_excerpt": "非具体商品依据：敏感肌宣称需要评价依据。",
    }], "available"))
    drafts = 0

    def draft(payload):
        nonlocal drafts
        drafts += 1
        source = next(s for s in payload["sourceCatalog"] if s["kind"] == "knowledge")
        assert source["fields"]["scope"] == "general_consumer"
        body = "敏感肌适用性宣称需要评价依据。"
        if drafts == 2:
            assert any("从body复制连续原文" in issue for issue in payload["repairIssues"])
        result = json.loads(fixtures.OUTPUT)
        result["reply_suggestions"][0] = {
            "style": "recommended", "body": body,
            "claims": [{"text": body if drafts == 2 else "敏感肌宣称需要评价依据",
                        "source_refs": [source["sourceId"]]}],
        }
        return result

    make_provider(provider, draft)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["verificationStatus"] == "verified"
    assert result["modelUsage"]["calls"] == 3
    assert drafts == 2


def test_fabricated_memory_is_never_saved_and_failure_is_audited(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "查询物流")

    def draft(payload):
        value = json.loads(fixtures.OUTPUT)
        value["memory"] = [{"category": "known", "source_ref": "fabricated", "quote": "退款成功"}]
        return value

    make_provider(provider, draft)
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 400
    assert not client.get(f"/api/support/reception/{cid}/memory", headers=SUPPORT).json()["items"]
    with factory() as session:
        run = session.scalar(select(AssistantRunRow).where(AssistantRunRow.conversation_id == cid))
        assert run.status == "failed"
        assert json.loads(run.usage_json)["calls"] == 2
        assert json.loads(run.trace_json)[-1]["issues"]


def test_memory_sources_follow_explicit_customer_scope_not_another_customers_messages(workspace):
    client, factory, _ = workspace
    cids = []
    for owner, text in [("owner-a", "我是干皮"), ("owner-a", "接着上次的问题"), ("owner-b", "另一位客户的私有描述")]:
        c = client.post("/api/customer/conversations", headers=CUSTOMER, json={"customerId": owner}).json()
        cids.append(c["conversationId"])
        fixtures._send(client, c["conversationId"], text)
    with factory() as session:
        sources = collect_sources(session, cids[1])
    text = "\n".join(s.text for s in sources)
    assert "我是干皮" in text
    assert "另一位客户的私有描述" not in text


def test_invalid_verifier_output_preserves_both_call_costs_without_saving_memory(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "查询物流")
    make_provider(provider, lambda _: json.loads(fixtures.OUTPUT), lambda _: {"invalid": True})
    response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert response.status_code == 400
    assert not client.get(f"/api/support/reception/{cid}/memory", headers=SUPPORT).json()["items"]
    with factory() as session:
        run = session.scalar(select(AssistantRunRow).where(AssistantRunRow.conversation_id == cid))
        assert run.status == "failed"
        usage = json.loads(run.usage_json)
        assert usage["calls"] == 2
        assert usage["promptTokens"] == 160
        assert usage["inputCharacters"] == sum(
            len(message.content) for call in provider.calls for message in call
        )
        assert json.loads(run.trace_json)[-1]["status"] == "failed"
