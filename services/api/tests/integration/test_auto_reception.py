import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures

from app.domain.consumer_service.auto_reception import (
    expire_jobs,
    process_job,
    utcnow,
    validate_auto_reply,
    wants_human,
)
from app.domain.consumer_service.models import AssistantRunRow, AutoReplyJobRow, ServiceMemoryRow
from app.errors import ModelOutputInvalid
from app.integrations.model_provider import ChatResult

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def jobs(factory, cid):
    with factory() as session:
        return list(
            session.scalars(
                select(AutoReplyJobRow)
                .where(
                    AutoReplyJobRow.conversation_id == cid,
                )
                .order_by(AutoReplyJobRow.message_revision)
            )
        )


def replies(client, cid):
    return [
        m
        for m in client.get(
            f"/api/customer/conversations/{cid}/messages",
            headers=CUSTOMER,
        ).json()
        if m["senderRole"] == "assistant"
    ]


def test_default_auto_reception_and_idempotence(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    baseline = len(replies(client, cid))
    sent = fixtures._send(client, cid, "包裹到哪了")
    assert sent["reply"] is None  # Ack immediately, worker delivers separately.
    job = jobs(factory, cid)[0]
    assert job.status == "queued" and not provider.calls
    process_job(client.app.state.runtime, job.job_id)
    assert len(provider.calls) == 2
    assert len(replies(client, cid)) == baseline + 1
    assert jobs(factory, cid)[0].status == "sent"
    assert "AI自动接待模式" in provider.calls[0][0].content
    fixtures._send(client, cid, "包裹到哪了")
    process_job(client.app.state.runtime, job.job_id)
    assert len(provider.calls) == 2
    assert len(jobs(factory, cid)) == 1


def test_customer_handoff_cancels_queued_reply(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid)
    job = jobs(factory, cid)[0]
    response = client.post(f"/api/customer/conversations/{cid}/handoff", headers=CUSTOMER)
    assert response.status_code == 200
    assert response.json()["serviceMode"] == "operator_assisted"
    process_job(client.app.state.runtime, job.job_id)
    assert not provider.calls and jobs(factory, cid)[0].status == "cancelled"
    queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()
    item = next(r for r in queue["items"] if r["conversationId"] == cid)
    assert item["handoffReason"] == "客户要求人工"


def test_explicit_human_request_and_resume_are_separate(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "请转人工客服")
    assert not jobs(factory, cid)
    assert not provider.calls
    manual = client.post(
        f"/api/support/reception/{cid}/messages",
        headers=SUPPORT,
        json={"body": "我来跟进", "clientMessageKey": "operator-1"},
    )
    assert manual.status_code == 200
    resumed = client.post(
        f"/api/support/reception/{cid}/service-mode", headers=SUPPORT, json={"mode": "autonomous"}
    )
    assert resumed.status_code == 200
    assert not jobs(factory, cid)  # No replay of messages handled by a person.
    rejected = client.post(
        f"/api/support/reception/{cid}/messages",
        headers=SUPPORT,
        json={"body": "不应发出", "clientMessageKey": "operator-2"},
    )
    assert rejected.status_code == 409
    fixtures._send(client, cid, "继续查一下物流", key="next")
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    assert len(provider.calls) == 2


def test_takeover_while_model_is_running_discards_reply(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid)
    baseline = len(replies(client, cid))
    original = provider.complete

    def delayed(messages, **kwargs):
        response = client.post(
            f"/api/support/reception/{cid}/service-mode",
            headers=SUPPORT,
            json={"mode": "operator_assisted"},
        )
        assert response.status_code == 200
        return original(messages, **kwargs)

    provider.complete = delayed
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    assert len(replies(client, cid)) == baseline
    assert jobs(factory, cid)[0].status == "cancelled"
    assert len(provider.calls) == 1  # Takeover prevents a second, verifier request.


def test_new_message_supersedes_inflight_generation(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "先查物流")
    original = provider.complete

    def delayed(messages, **kwargs):
        fixtures._send(client, cid, "补充订单信息", key="second")
        provider.complete = original
        return original(messages, **kwargs)

    provider.complete = delayed
    first = jobs(factory, cid)[0]
    baseline = len(replies(client, cid))
    process_job(client.app.state.runtime, first.job_id)
    assert len(replies(client, cid)) == baseline
    process_job(client.app.state.runtime, first.job_id)
    latest = jobs(factory, cid)[-1]
    process_job(client.app.state.runtime, latest.job_id)
    assert len(replies(client, cid)) == baseline + 1
    messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    revisions = [m["messageRevision"] for m in messages]
    assert len(revisions) == len(set(revisions))


def test_previous_ai_question_is_dialogue_context_but_not_factual_authority(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "咨询一下订单")
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    previous = replies(client, cid)[-1]["body"]
    fixtures._send(client, cid, "是的", key="short-answer")
    process_job(client.app.state.runtime, jobs(factory, cid)[-1].job_id)
    payload = json.loads(provider.calls[2][1].content)
    assert any(m["role"] == "assistant" and m["body"] == previous for m in payload["recentConversation"])
    assert not any(s["text"] == previous for s in payload["sourceCatalog"])
    assert payload["latestCustomerMessage"] == "是的"


@pytest.mark.parametrize("failure", ["provider", "unsupported_amount", "handoff"])
def test_failed_or_unsafe_generation_transfers_without_losing_customer_message(workspace, failure):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "咨询物流")
    baseline = len(replies(client, cid))

    def complete(messages, **kwargs):
        if messages[0].content.startswith("GROUNDING_REVIEW_V1"):
            return ChatResult(text='{"supported":true,"issues":[]}', model="test",
                              latency_seconds=0.01, is_mock=True)
        if failure == "provider":
            raise TimeoutError("test provider unavailable")
        payload = json.loads(fixtures.OUTPUT)
        if failure == "unsupported_amount":
            payload["reply_suggestions"][0]["body"] = "您的退款金额为999元。"
        else:
            payload["handoff_required"] = True
        return ChatResult(
            text=json.dumps(payload, ensure_ascii=False),
            model="test",
            latency_seconds=0.01,
            is_mock=True,
        )

    provider.complete = complete
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    assert jobs(factory, cid)[0].status == "handoff"
    assert len(replies(client, cid)) == baseline + (1 if failure == "handoff" else 0)
    messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert any(m["body"] == "咨询物流" for m in messages)
    assert messages[-1]["body"] == "已转人工，客服将继续跟进。"
    assert not any("riskTypes" in str(m) or "knowledgeEvidence" in str(m) for m in messages)
    if failure == "provider":
        with factory() as session:
            run = session.scalar(select(AssistantRunRow).where(AssistantRunRow.conversation_id == cid))
            usage = json.loads(run.usage_json)
            assert usage["calls"] == 1
            assert usage["promptTokens"] is None


def test_high_risk_is_transferred_without_model_call(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "使用后脸肿，已经就医")
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    assert not provider.calls
    assert jobs(factory, cid)[0].error_code == "safety_review"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("转人工", True),
        ("请找人工客服", True),
        ("不需要人工客服", False),
        ("不用转人工，帮我看订单", False),
        ("刚才不需要人工，现在还是转人工吧", True),
    ],
)
def test_human_request_matching(text, expected):
    assert wants_human(text) is expected


def test_customer_cannot_resume_autonomous_mode(workspace):
    client, _, _ = workspace
    cid = fixtures._create(client)
    assert (
        client.post(
            f"/api/support/reception/{cid}/service-mode",
            headers=CUSTOMER,
            json={"mode": "autonomous"},
        ).status_code
        == 403
    )


@pytest.mark.parametrize("status", ["queued", "running"])
def test_total_timeout_transfers_queued_or_running_jobs(workspace, status):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid)
    with factory() as session:
        job = session.scalar(select(AutoReplyJobRow).where(AutoReplyJobRow.conversation_id == cid))
        job.status = status
        job.created_at = utcnow() - timedelta(seconds=60)
        session.commit()
    expire_jobs(client.app.state.runtime)
    job = jobs(factory, cid)[0]
    assert job.status == "handoff" and job.error_code == "reply_timeout"
    assert not provider.calls


def test_processing_expired_queue_does_not_call_model_without_periodic_expiry(workspace):
    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid)
    with factory() as session:
        job = session.scalar(select(AutoReplyJobRow).where(AutoReplyJobRow.conversation_id == cid))
        job.created_at = utcnow() - timedelta(seconds=60)
        job_id = job.job_id
        session.commit()
    baseline = len(replies(client, cid))
    process_job(client.app.state.runtime, job_id)
    assert jobs(factory, cid)[0].error_code == "reply_timeout"
    assert len(replies(client, cid)) == baseline
    assert not provider.calls


def test_queue_wait_is_subtracted_from_the_first_model_request(workspace, monkeypatch):
    from app.domain.consumer_service import auto_reception

    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid)
    now = utcnow()
    monkeypatch.setattr(auto_reception, "utcnow", lambda: now)
    with factory() as session:
        job = session.scalar(select(AutoReplyJobRow).where(AutoReplyJobRow.conversation_id == cid))
        job.created_at = now - timedelta(seconds=30)
        job_id = job.job_id
        session.commit()
    original = provider.complete
    budgets = []

    def complete(messages, **kwargs):
        budgets.append(kwargs["timeout_seconds"])
        return original(messages, **kwargs)

    provider.complete = complete
    process_job(client.app.state.runtime, job_id)
    assert len(budgets) == 2
    assert all(0 < budget <= 15 for budget in budgets)
    assert budgets[1] <= budgets[0]
    assert jobs(factory, cid)[0].status == "sent"


def test_late_model_result_hands_off_without_verification_but_keeps_usage(workspace, monkeypatch):
    from app.domain.consumer_service import grounded_workflow

    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid)
    baseline = len(replies(client, cid))
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(grounded_workflow, "monotonic", lambda: clock.now)

    def complete(messages, **kwargs):
        provider._calls.append(list(messages))
        clock.now += kwargs["timeout_seconds"] + 1
        return ChatResult(text=fixtures.OUTPUT, model="late-fixture", is_mock=True,
                          latency_seconds=50, prompt_tokens=100, completion_tokens=20)

    provider.complete = complete
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    assert len(provider.calls) == 1
    assert jobs(factory, cid)[0].status == "handoff"
    assert jobs(factory, cid)[0].error_code == "reply_timeout"
    assert len(replies(client, cid)) == baseline
    with factory() as session:
        run = session.scalar(select(AssistantRunRow).where(AssistantRunRow.conversation_id == cid))
        assert run.error_code == "provider_timeout"
        assert json.loads(run.usage_json)["promptTokens"] == 100
        assert json.loads(run.usage_json)["calls"] == 1
        assert session.get(ServiceMemoryRow, cid) is None


@pytest.mark.parametrize("model_requested_handoff", [False, True])
@pytest.mark.parametrize("expiry_stage", ["validation", "input_hash"])
def test_deadline_expiring_after_generation_cannot_deliver_a_reply(
    workspace, monkeypatch, model_requested_handoff, expiry_stage,
):
    from app.domain.consumer_service import auto_reception
    from app.domain.consumer_service import workspace as reception_workspace

    client, factory, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid)
    baseline = len(replies(client, cid))
    clock = SimpleNamespace(now=utcnow())
    monkeypatch.setattr(auto_reception, "utcnow", lambda: clock.now)
    original_validate = auto_reception.validate_auto_reply
    original_complete = provider.complete
    original_hash = reception_workspace.assistant_input_hash
    validated = False

    def complete(messages, **kwargs):
        result = original_complete(messages, **kwargs)
        if model_requested_handoff and not messages[0].content.startswith("GROUNDING_REVIEW_V1"):
            payload = json.loads(result.text)
            payload["handoff_required"] = True
            return ChatResult(text=json.dumps(payload), model=result.model, is_mock=True,
                              latency_seconds=0)
        return result

    def late_validation(*args, **kwargs):
        nonlocal validated
        original_validate(*args, **kwargs)
        validated = True
        if expiry_stage == "validation":
            clock.now += timedelta(seconds=50)

    def late_hash(*args, **kwargs):
        result = original_hash(*args, **kwargs)
        if validated and expiry_stage == "input_hash":
            clock.now += timedelta(seconds=50)
        return result

    provider.complete = complete
    monkeypatch.setattr(auto_reception, "validate_auto_reply", late_validation)
    monkeypatch.setattr(reception_workspace, "assistant_input_hash", late_hash)
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    assert len(provider.calls) == 2
    assert jobs(factory, cid)[0].error_code == "reply_timeout"
    assert len(replies(client, cid)) == baseline
    mode = next(row for row in client.get("/api/support/reception/queue", headers=SUPPORT).json()["items"]
                if row["conversationId"] == cid)
    assert mode["serviceMode"] == "operator_assisted"
    assert mode["handoffReason"] == "AI回复超时"


def test_prefixed_source_identifiers_are_allowed_but_invented_ones_are_not():
    context = SimpleNamespace(orders=[], work_orders=[
        SimpleNamespace(work_order_id="BH919209358357",
                        detail={"reshipTrackingNo": "YT7667875838478"})
    ])
    validate_auto_reply("工单BH919209358357对应的补发单号为YT7667875838478。", context)
    with pytest.raises(ModelOutputInvalid):
        validate_auto_reply("补发单号为YT9999999999999。", context)
