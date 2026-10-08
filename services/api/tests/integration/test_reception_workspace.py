from __future__ import annotations

import io
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.domain.case_state.models import Base, MessageRow
from app.domain.consumer_service.auto_reception import process_job
from app.domain.consumer_service.importer import import_business_workbook
from app.domain.consumer_service.models import AutoReplyJobRow, SourceRecordRow
from app.domain.platform.settings import ensure_builtin_templates, get_enabled_template
from app.integrations.embedding_provider import MockEmbeddingProvider
from app.integrations.model_provider import ChatResult, MockModelProvider
from app.knowledge.models import Base as KnowledgeBase
from app.main import create_app
from app.runtime import RuntimeContext

SUPPORT = {"X-Demo-View-Role": "support"}
CUSTOMER = {"X-Demo-View-Role": "customer"}
SOURCE = Path(r"D:\下载\赛题 1：数据共情者-业务数据.xlsx")
OUTPUT = json.dumps(
    {
        "current_question": "查询订单物流",
        "service_summary": "消费者询问订单进度。",
        "emotion_level": "calm",
        "missing_information": ["订单号"],
        "next_steps": ["核对订单"],
        "reply_suggestions": [
            {"style": "recommended", "body": "我来核对这笔订单，方便提供订单号吗？"}
        ],
    },
    ensure_ascii=False,
)


class GroundedFixtureProvider(MockModelProvider):
    """Explicit test double for the new verification step, not a live quality verdict."""

    def complete(self, messages, **kwargs):
        if messages[0].content.startswith("GROUNDING_REVIEW_V1"):
            self._calls.append(list(messages))
            return ChatResult(text='{"supported":true,"issues":[]}', model=self.model_id,
                              latency_seconds=0, is_mock=True)
        return super().complete(messages, **kwargs)


@pytest.fixture
def workspace(tmp_path):
    engine = build_engine(
        Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'reception.sqlite3'}")
    )
    Base.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as session:
        import_business_workbook(session, SOURCE, repo_root=tmp_path)
        ensure_builtin_templates(session)
        session.commit()
    provider = GroundedFixtureProvider(responses=[OUTPUT] * 10)
    context = RuntimeContext(
        settings=Settings(run_mode="mock", runtime_dir=str(tmp_path / "runtime")),
        engine=engine,
        session_factory=factory,
        model_provider=provider,
        embedding_provider=MockEmbeddingProvider(reason="test"),
    )
    app = create_app()

    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = context
        yield
        context.close()

    app.router.lifespan_context = lifespan
    with TestClient(app) as client:
        yield client, factory, provider


def _create(client):
    response = client.post("/api/customer/conversations", json={}, headers=CUSTOMER)
    assert response.status_code == 200
    return response.json()["conversationId"]


def _send(client, conversation_id, body="查询订单物流", key="customer-1"):
    response = client.post(
        f"/api/customer/conversations/{conversation_id}/messages",
        json={"body": body, "clientMessageKey": key},
        headers=CUSTOMER,
    )
    assert response.status_code == 200
    return response.json()


def test_new_conversation_visible_and_bidirectional_messages(workspace):
    client, _factory, provider = workspace
    conversation_id = _create(client)
    queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()
    assert queue["items"][0]["conversationId"] == conversation_id
    first = _send(client, conversation_id)
    assert first["reply"] is None
    repeated = _send(client, conversation_id)
    assert repeated["created"] is False
    assert repeated["message"]["messageId"] == first["message"]["messageId"]
    queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()
    assert queue["unreadTotal"] == 1
    client.post(f"/api/support/reception/{conversation_id}/service-mode",
                headers=SUPPORT, json={"mode": "operator_assisted"})
    response = client.post(
        f"/api/support/reception/{conversation_id}/messages",
        json={"body": "请提供订单号", "clientMessageKey": "operator-1"},
        headers=SUPPORT,
    )
    assert response.status_code == 200
    customer_messages = client.get(
        f"/api/customer/conversations/{conversation_id}/messages", headers=CUSTOMER
    ).json()
    assert customer_messages[-1]["senderRole"] == "operator"
    assert customer_messages[-1]["body"] == "请提供订单号"
    assert provider.calls == []


@pytest.mark.parametrize("sender", ["customer", "support"])
def test_image_only_messages_visible_on_both_sides(workspace, sender):
    from PIL import Image

    client, factory, _provider = workspace
    cid = _create(client)
    client.post(f"/api/support/reception/{cid}/service-mode",
                headers=SUPPORT, json={"mode": "operator_assisted"})
    if sender == "support":
        from app.domain.consumer_service.risk_rules import evaluate_risks

        _send(client, cid, "亲，这是什么商品呀？")
        now = datetime.now(UTC).replace(tzinfo=None)
        with factory() as session:
            rows = list(session.scalars(select(MessageRow).where(
                MessageRow.conversation_id == cid,
            ).order_by(MessageRow.applies_to_message_revision)))
            for index, row in enumerate(rows):
                row.created_at = now - timedelta(minutes=5, seconds=len(rows) - index)
            session.flush()
            signals = evaluate_risks(session, now=now)
            waiting = next(row for row in signals
                           if row.conversation_id == cid and row.risk_type == "response_wait")
            wait_id = waiting.alert_id
            assert waiting.risk_status == "pending"
            session.commit()
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(buffer, format="PNG")
    data = buffer.getvalue()
    base = f"/api/customer/conversations/{cid}" if sender == "customer" else f"/api/support/reception/{cid}"
    headers = CUSTOMER if sender == "customer" else SUPPORT
    uploaded = client.post(
        f"{base}/attachments", files={"file": ("product.png", data, "image/png")},
        headers=headers,
    )
    assert uploaded.status_code == 200, uploaded.text
    attachment_id = uploaded.json()["attachmentId"]
    payload = {"body": "", "clientMessageKey": f"{sender}-image", "attachmentIds": [attachment_id]}
    sent = client.post(f"{base}/messages", json=payload, headers=headers)
    assert sent.status_code == 200, sent.text
    if sender == "support":
        from app.domain.consumer_service.models import ServiceRiskAlertRow

        with factory() as session:
            assert session.get(ServiceRiskAlertRow, wait_id).risk_status == "resolved"
    for path, role in (
        (f"/api/customer/conversations/{cid}/messages", CUSTOMER),
        (f"/api/support/reception/{cid}/messages", SUPPORT),
    ):
        rows = client.get(path, headers=role).json()
        assert rows[-1]["attachments"][0]["attachmentId"] == attachment_id
        assert rows[-1]["senderRole"] == ("customer" if sender == "customer" else "operator")
        url = rows[-1]["attachments"][0]["url"]
        assert client.get(url).content == data
    repeated = client.post(f"{base}/messages", json=payload, headers=headers)
    assert repeated.status_code == 200
    other_cid = _create(client)
    client.post(f"/api/support/reception/{other_cid}/service-mode",
                headers=SUPPORT, json={"mode": "operator_assisted"})
    other_base = f"/api/customer/conversations/{other_cid}" if sender == "customer" else f"/api/support/reception/{other_cid}"
    assert client.post(f"{other_base}/messages", json=payload, headers=headers).status_code == 422
    if sender == "support":
        assert client.post(f"{base}/attachments", files={"file": ("product.png", data, "image/png")},
                           headers=CUSTOMER).status_code == 403


def test_unread_watermark_does_not_swallow_new_messages(workspace):
    client, _factory, _provider = workspace
    conversation_id = _create(client)
    _send(client, conversation_id)
    queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()
    revision = queue["items"][0]["messageRevision"]
    client.post(
        f"/api/support/reception/{conversation_id}/seen",
        json={"revision": revision},
        headers=SUPPORT,
    )
    assert client.get("/api/support/reception/queue", headers=SUPPORT).json()["unreadTotal"] == 0
    _send(client, conversation_id, key="customer-2")
    client.post(
        f"/api/support/reception/{conversation_id}/seen",
        json={"revision": revision},
        headers=SUPPORT,
    )
    assert client.get("/api/support/reception/queue", headers=SUPPORT).json()["unreadTotal"] == 1


def test_local_reads_do_not_call_model_and_post_generates(workspace):
    client, _factory, provider = workspace
    conversation_id = _create(client)
    _send(client, conversation_id)
    for path in [
        "/api/support/reception/queue",
        f"/api/support/reception/{conversation_id}/messages",
        f"/api/support/conversations/{conversation_id}/service-context",
        f"/api/support/conversations/{conversation_id}/assistant",
    ]:
        assert client.get(path, headers=SUPPORT).status_code == 200
    assert not provider.calls
    generated = client.post(f"/api/support/reception/{conversation_id}/assistant", headers=SUPPORT)
    assert generated.status_code == 200, generated.text
    assert generated.json()["isMock"] is True
    assert len(provider.calls) == 2
    cached = client.get(
        f"/api/support/conversations/{conversation_id}/assistant", headers=SUPPORT
    ).json()
    assert cached["observationId"] == generated.json()["observationId"]
    assert len(provider.calls) == 2


def test_assistant_cache_remains_fresh_after_automatic_delivery(workspace):
    client, factory, provider = workspace
    cid = _create(client)
    _send(client, cid, "查询订单物流")
    with factory() as session:
        job = session.scalar(select(AutoReplyJobRow).where(
            AutoReplyJobRow.conversation_id == cid,
        ))
        assert job is not None
        job_id = job.job_id
    process_job(client.app.state.runtime, job_id)
    cached = client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT).json()
    assert cached["stale"] is False
    assert len(provider.calls) == 2


def test_prompt_edit_used_and_stales_previous_result(workspace):
    client, factory, provider = workspace
    conversation_id = _create(client)
    _send(client, conversation_id)
    generated = client.post(f"/api/support/reception/{conversation_id}/assistant", headers=SUPPORT)
    assert generated.status_code == 200
    with factory() as session:
        template = get_enabled_template(session, "LOREAL_ASSISTANT")
        template.content += "\nTEST-PROMPT-EDIT"
        template.revision += 1
        session.commit()
    cached = client.get(
        f"/api/support/conversations/{conversation_id}/assistant", headers=SUPPORT
    ).json()
    assert cached["stale"] is True
    assert (
        client.post(
            f"/api/support/reception/{conversation_id}/assistant", headers=SUPPORT
        ).status_code
        == 200
    )
    assert any("TEST-PROMPT-EDIT" in messages[0].content for messages in provider.calls)


def test_adoption_never_sends_and_new_message_expires_suggestion(workspace):
    client, factory, _provider = workspace
    conversation_id = _create(client)
    _send(client, conversation_id)
    result = client.post(
        f"/api/support/reception/{conversation_id}/assistant", headers=SUPPORT
    ).json()
    action = {"inputHash": result["inputHash"], "style": "recommended", "action": "adopt"}
    with factory() as session:
        before = len(list(session.scalars(select(MessageRow))))
    assert (
        client.post(
            f"/api/support/reception/{conversation_id}/suggestion-action",
            json=action,
            headers=SUPPORT,
        ).status_code
        == 200
    )
    with factory() as session:
        assert len(list(session.scalars(select(MessageRow)))) == before
    _send(client, conversation_id, key="customer-2")
    assert (
        client.post(
            f"/api/support/reception/{conversation_id}/suggestion-action",
            json=action,
            headers=SUPPORT,
        ).status_code
        == 409
    )


def test_product_and_service_nodes_from_source_not_duplicate_chats(workspace):
    client, factory, _provider = workspace
    context = client.get(
        "/api/support/conversations/S00001/service-context", headers=SUPPORT
    ).json()
    assert context["products"]
    assert context["products"][0]["sku"]
    assert context["serviceNodes"]
    assert all(node["kind"] != "message" for node in context["serviceNodes"])
    before_messages = client.get("/api/support/reception/S00001/messages", headers=SUPPORT).json()
    with factory() as session:
        before = [
            (row.record_id, row.values_json) for row in session.scalars(select(SourceRecordRow))
        ]
    sent = client.post(
        "/api/support/reception/S00001/messages",
        json={"body": "我来核对", "clientMessageKey": "source-reply"},
        headers=SUPPORT,
    )
    assert sent.status_code == 200
    after_messages = client.get("/api/support/reception/S00001/messages", headers=SUPPORT).json()
    assert len(after_messages) == len(before_messages) + 1
    with factory() as session:
        assert [
            (row.record_id, row.values_json) for row in session.scalars(select(SourceRecordRow))
        ] == before


def test_work_orders_are_80_independent_records(workspace):
    client, _factory, _provider = workspace
    response = client.get("/api/support/reception/work-orders/all", headers=SUPPORT)
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 80
    assert len({row["workOrderId"] for row in rows}) == 80
    assert len({row["workOrderType"] for row in rows}) == 5


@pytest.mark.parametrize(
    "path",
    [
        "/api/support/reception/queue",
        "/api/support/reception/S00001/messages",
        "/api/support/reception/work-orders/all",
        "/api/support/conversations/S00001/service-context",
        "/api/support/conversations/S00001/assistant",
    ],
)
def test_customer_cannot_read_support_workspace(workspace, path):
    client, _factory, _provider = workspace
    response = client.get(path, headers=CUSTOMER)
    assert response.status_code == 403
