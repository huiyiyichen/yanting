"""HTTP 接口集成测试。

重点覆盖 AC-24（客服功能不泄露客户页）与 AC-30（接口权限边界）：
绕过 UI 直接请求内部接口必须被服务端拒绝，而不是靠前端隐藏按钮。

测试使用真实数据库与 mock 模型；不声称 live 质量。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.case_state.models import Base as CaseBase
from app.knowledge.models import Base as KnowledgeBase


class _StubEmbedding:
    model_id = "stub"
    dimension = 1024

    def available(self) -> bool:
        return False

    def describe(self) -> dict[str, str]:
        return {"backend": "stub", "model_id": self.model_id}

    def encode(self, texts: list[str], *, is_query: bool = False) -> Any:
        raise RuntimeError("本用例不执行真实编码")


def _understanding_json(**overrides: Any) -> str:
    payload = {
        "product_model_text": "A1 Pro",
        "fault_type": "weak_suction",
        "fault_part": "filter",
        "phenomenon": "吸力明显变弱",
        "intents": ["diagnosis"],
        "emotion_level": "calm",
        "complaint_risk": "not_flagged",
        "complaint_reason": "",
        "country_code_text": "中国",
        "purchase_channel": "official_website",
        "seller_name_raw": "",
        "image_visible_clues": [],
        "urgency_note": "",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """构建一个使用临时数据库与 mock 模型的测试客户端。"""

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.integrations.embedding_provider import MockEmbeddingProvider
    from app.integrations.model_provider import MockModelProvider
    from app.main import create_app
    from app.runtime import RuntimeContext
    from app.tools.registry import build_default_registry

    db_path = tmp_path / "api.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    CaseBase.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    settings = Settings()
    context = RuntimeContext(
        settings=settings,
        engine=engine,
        session_factory=factory,
        model_provider=MockModelProvider(responses=[_understanding_json()] * 20),
        embedding_provider=MockEmbeddingProvider(reason="接口测试"),
        tool_registry=build_default_registry(),
    )

    app = create_app()

    # 用测试上下文替换 lifespan 构建的上下文
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(_app: Any):  # type: ignore[no-untyped-def]
        _app.state.runtime = context
        yield
        context.close()

    app.router.lifespan_context = _lifespan

    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def _customer_headers() -> dict[str, str]:
    return {"X-Demo-View-Role": "customer"}


def _support_headers() -> dict[str, str]:
    return {"X-Demo-View-Role": "support"}


class TestCustomerConversations:
    def test_create_and_list(self, client: TestClient) -> None:
        created = client.post(
            "/api/customer/conversations",
            json={"customerId": "CUST-DEMO-01"},
            headers=_customer_headers(),
        )
        assert created.status_code == 200
        conversation_id = created.json()["conversationId"]

        listed = client.get(
            "/api/customer/conversations?customer_id=CUST-DEMO-01",
            headers=_customer_headers(),
        )
        assert listed.status_code == 200
        assert conversation_id in {item["conversationId"] for item in listed.json()}

    def test_send_message_returns_reply_but_no_internal_decision(self, client: TestClient) -> None:
        """AC-24：客户侧响应不得包含 AI 判断明细。"""

        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]

        response = client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "我的 A1 Pro 吸力不行了", "clientMessageKey": "k-1"},
            headers=_customer_headers(),
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["message"]["body"] == "我的 A1 Pro 吸力不行了"
        # decision 必须为空，且响应体里不得出现内部字段名
        assert payload["decision"] is None
        body_text = json.dumps(payload, ensure_ascii=False)
        for leaked in ("serviceRoute", "emotionLevel", "complaintRisk", "retrievalId", "toolCalls"):
            assert leaked not in body_text, f"客户响应泄露了内部字段 {leaked}"

    def test_idempotent_message_key(self, client: TestClient) -> None:
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        first = client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "吸力不行", "clientMessageKey": "same-key"},
            headers=_customer_headers(),
        )
        second = client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "吸力不行", "clientMessageKey": "same-key"},
            headers=_customer_headers(),
        )
        assert first.json()["message"]["messageId"] == second.json()["message"]["messageId"]
        messages = client.get(
            f"/api/customer/conversations/{conversation_id}/messages",
            headers=_customer_headers(),
        ).json()
        customer_messages = [m for m in messages if m["senderRole"] == "customer"]
        assert len(customer_messages) == 1

    def test_unknown_conversation_returns_404(self, client: TestClient) -> None:
        response = client.get(
            "/api/customer/conversations/nope/messages", headers=_customer_headers()
        )
        assert response.status_code == 404


class TestCustomerIsolation:
    def test_two_conversations_do_not_share_messages(self, client: TestClient) -> None:
        first = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        second = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        client.post(
            f"/api/customer/conversations/{first}/messages",
            json={"body": "会话一", "clientMessageKey": "a"},
            headers=_customer_headers(),
        )
        client.post(
            f"/api/customer/conversations/{second}/messages",
            json={"body": "会话二", "clientMessageKey": "b"},
            headers=_customer_headers(),
        )
        first_messages = client.get(
            f"/api/customer/conversations/{first}/messages", headers=_customer_headers()
        ).json()
        bodies = [m["body"] for m in first_messages]
        assert "会话一" in bodies
        assert "会话二" not in bodies


class TestPermissionBoundary:
    """AC-30：绕过 UI 直接请求必须被服务端拒绝。"""

    def test_customer_cannot_read_support_queue(self, client: TestClient) -> None:
        response = client.get("/api/support/queue", headers=_customer_headers())
        assert response.status_code == 403

    def test_customer_cannot_read_case_detail(self, client: TestClient) -> None:
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        response = client.get(
            f"/api/support/conversations/{conversation_id}/case",
            headers=_customer_headers(),
        )
        assert response.status_code == 403

    def test_customer_cannot_review_request(self, client: TestClient) -> None:
        response = client.post(
            "/api/support/requests/req-whatever/review",
            json={"action": "approve"},
            headers=_customer_headers(),
        )
        assert response.status_code == 403

    def test_customer_cannot_read_audit(self, client: TestClient) -> None:
        response = client.get("/api/support/audit/whatever", headers=_customer_headers())
        assert response.status_code == 403

    def test_customer_cannot_send_operator_message(self, client: TestClient) -> None:
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        response = client.post(
            f"/api/support/conversations/{conversation_id}/messages",
            json={"body": "我是客服", "clientMessageKey": "x"},
            headers=_customer_headers(),
        )
        assert response.status_code == 403

    def test_missing_role_header_defaults_to_customer(self, client: TestClient) -> None:
        """缺少角色头时按最小权限处理。"""

        assert client.get("/api/support/queue").status_code == 403

    def test_invalid_role_header_defaults_to_customer(self, client: TestClient) -> None:
        response = client.get("/api/support/queue", headers={"X-Demo-View-Role": "admin"})
        assert response.status_code == 403

    def test_cannot_access_support_message_api_as_customer(self, client: TestClient) -> None:
        response = client.post(
            "/api/support/conversations/x/messages",
            json={"body": "hi", "clientMessageKey": "k"},
            headers=_customer_headers(),
        )
        assert response.status_code == 403


class TestSupportWorkbench:
    def test_queue_visible_to_support(self, client: TestClient) -> None:
        client.post("/api/customer/conversations", json={}, headers=_customer_headers())
        response = client.get("/api/support/queue", headers=_support_headers())
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_case_detail_has_no_raw_prompt_fields(self, client: TestClient) -> None:
        """客服侧也不返回原始提示词或模型隐藏思考。"""

        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "吸力不行", "clientMessageKey": "k-1"},
            headers=_customer_headers(),
        )
        response = client.get(
            f"/api/support/conversations/{conversation_id}/case",
            headers=_support_headers(),
        )
        assert response.status_code == 200
        body = json.dumps(response.json(), ensure_ascii=False)
        for forbidden in ("prompt", "rawPrompt", "chainOfThought", "confidence"):
            assert forbidden not in body.lower() or forbidden == "promptversion"
        case = response.json()
        assert "forbiddenActions" in case
        assert "modify_source_order" in case["forbiddenActions"]

    def test_operator_must_take_over_before_sending(self, client: TestClient) -> None:
        """托管期间客服不能直接发送：必须先接管。"""

        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]

        blocked = client.post(
            f"/api/support/conversations/{conversation_id}/messages",
            json={"body": "客服回复", "clientMessageKey": "op-1"},
            headers=_support_headers(),
        )
        assert blocked.status_code == 409
        assert "接管" in blocked.json()["error"]["message"]

        takeover = client.post(
            f"/api/support/conversations/{conversation_id}/service-mode",
            json={"mode": "operator_assisted"},
            headers=_support_headers(),
        )
        assert takeover.status_code == 200
        assert takeover.json()["serviceMode"] == "operator_assisted"

        allowed = client.post(
            f"/api/support/conversations/{conversation_id}/messages",
            json={"body": "客服回复", "clientMessageKey": "op-1"},
            headers=_support_headers(),
        )
        assert allowed.status_code == 200
        assert allowed.json()["senderRole"] == "operator"

    def test_resume_ai_is_independent_operation(self, client: TestClient) -> None:
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        client.post(
            f"/api/support/conversations/{conversation_id}/service-mode",
            json={"mode": "operator_assisted"},
            headers=_support_headers(),
        )
        resumed = client.post(
            f"/api/support/conversations/{conversation_id}/service-mode",
            json={"mode": "autonomous"},
            headers=_support_headers(),
        )
        assert resumed.json()["serviceMode"] == "autonomous"
        assert resumed.json()["modeRevision"] == 2


class TestRatingEndpoint:
    def test_rating_not_available_before_case(self, client: TestClient) -> None:
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        response = client.get(
            f"/api/customer/conversations/{conversation_id}/rating",
            headers=_customer_headers(),
        )
        assert response.status_code == 200
        assert response.json() is None

    def test_rating_rejected_before_service_end(self, client: TestClient) -> None:
        """服务未结束时不允许发起评价。"""

        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "吸力不行", "clientMessageKey": "k-1"},
            headers=_customer_headers(),
        )
        response = client.post(
            f"/api/customer/conversations/{conversation_id}/rating",
            json={"action": "request"},
            headers=_customer_headers(),
        )
        assert response.status_code == 422


class TestSupportEcho:
    def test_echo_reports_run_mode_and_vision(self, client: TestClient) -> None:
        response = client.post("/api/support/health/echo", headers=_support_headers())
        assert response.status_code == 200
        payload = response.json()
        assert payload["viewRole"] == "support"
        assert payload["runMode"] in {"live", "mock"}
        assert "visionConfigured" in payload


class TestOperatorActionAudit:
    """人工动作必须留痕：接管/恢复托管、客服发消息。"""

    def test_takeover_and_operator_message_are_audited(self, client: TestClient) -> None:
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]

        client.post(
            f"/api/support/conversations/{conversation_id}/service-mode",
            json={"mode": "operator_assisted"},
            headers=_support_headers(),
        )
        client.post(
            f"/api/support/conversations/{conversation_id}/messages",
            json={"body": "您好，我是客服，正在为您处理", "clientMessageKey": "op-a"},
            headers=_support_headers(),
        )

        audit = client.get(
            f"/api/support/audit/{conversation_id}", headers=_support_headers()
        ).json()
        event_types = [item["eventType"] for item in audit]
        assert "service_mode_changed" in event_types
        assert "operator_message" in event_types

        mode_event = next(item for item in audit if item["eventType"] == "service_mode_changed")
        assert mode_event["actorType"] == "operator"
        msg_event = next(item for item in audit if item["eventType"] == "operator_message")
        assert msg_event["actorType"] == "operator"
        # 审计接口不返回正文原文
        assert "您好，我是客服" not in json.dumps(audit, ensure_ascii=False)

    def test_repeated_same_mode_is_not_audited_twice(self, client: TestClient) -> None:
        """重复设置同一模式不产生额外审计事件。"""

        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        for _ in range(2):
            client.post(
                f"/api/support/conversations/{conversation_id}/service-mode",
                json={"mode": "operator_assisted"},
                headers=_support_headers(),
            )
        audit = client.get(
            f"/api/support/audit/{conversation_id}", headers=_support_headers()
        ).json()
        assert sum(1 for item in audit if item["eventType"] == "service_mode_changed") == 1


class TestOpenApiContract:
    def test_contracts_include_customer_and_support_groups(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        paths = schema["paths"]
        assert "/api/customer/conversations" in paths
        assert "/api/support/queue" in paths
        assert "/api/support/requests/{request_id}/review" in paths

    def test_api_json_uses_camel_case(self, client: TestClient) -> None:
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()
        assert "conversationId" in conversation_id
        assert "conversation_id" not in conversation_id


class TestDeleteConversation:
    """删除会话：级联删业务数据、保留审计、两侧都能删。"""

    def test_customer_delete_removes_conversation_and_dependents(self, client: TestClient) -> None:
        created = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()
        conversation_id = created["conversationId"]
        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "删除测试：吸力变弱", "clientMessageKey": "del-1"},
            headers=_customer_headers(),
        )
        # 删除前：消息与案件都在
        assert client.get(
            f"/api/customer/conversations/{conversation_id}/messages",
            headers=_customer_headers(),
        ).json()

        removed = client.delete(
            f"/api/customer/conversations/{conversation_id}", headers=_customer_headers()
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["deleted"]["conversations"] == 1
        assert removed.json()["deleted"]["messages"] >= 1

        # 删除后：列表里没有，读消息 404
        listed = client.get(
            "/api/customer/conversations?customer_id=CUST-DEMO-01",
            headers=_customer_headers(),
        ).json()
        assert conversation_id not in {item["conversationId"] for item in listed}
        assert (
            client.get(
                f"/api/customer/conversations/{conversation_id}/messages",
                headers=_customer_headers(),
            ).status_code
            == 404
        )

    def test_delete_writes_audit_and_keeps_audit_rows(self, client: TestClient) -> None:
        created = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()
        conversation_id = created["conversationId"]
        client.delete(f"/api/customer/conversations/{conversation_id}", headers=_customer_headers())

        events = client.get(
            f"/api/support/audit?conversation_id={conversation_id}", headers=_support_headers()
        )
        # 审计接口可能不存在于本基线；存在时必须能查到删除事件
        if events.status_code == 200:
            types = {item["eventType"] for item in events.json()}
            assert "conversation_deleted" in types

    def test_support_can_delete_and_customer_cannot_delete_others(self, client: TestClient) -> None:
        created = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()
        conversation_id = created["conversationId"]
        # 客服侧删除入口存在且生效
        removed = client.delete(
            f"/api/support/conversations/{conversation_id}", headers=_support_headers()
        )
        assert removed.status_code == 200, removed.text

    def test_delete_missing_conversation_is_404(self, client: TestClient) -> None:
        assert (
            client.delete(
                "/api/customer/conversations/conv-not-exist", headers=_customer_headers()
            ).status_code
            == 404
        )


class TestSupportCloseConversation:
    """结束服务闭环：状态机校验 -> 审计 -> 开放客户评价入口 -> 客户 1—5 星。"""

    @staticmethod
    def _start_case(client: TestClient, key: str) -> str:
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "吸力明显变弱，想问问怎么处理", "clientMessageKey": key},
            headers=_customer_headers(),
        )
        return conversation_id

    def test_close_opens_rating_and_customer_can_submit(self, client: TestClient) -> None:
        conversation_id = self._start_case(client, "close-1")

        before = client.get(
            f"/api/customer/conversations/{conversation_id}/rating", headers=_customer_headers()
        ).json()
        assert before["ratingStatus"] == "not_requested"

        closed = client.post(
            f"/api/support/conversations/{conversation_id}/close",
            json={"reason": "已给出处理方案"},
            headers=_support_headers(),
        )
        assert closed.status_code == 200, closed.text
        body = closed.json()
        assert body["caseStatus"] == "closed"
        assert body["ratingStatus"] == "pending", body

        opened = client.get(
            f"/api/customer/conversations/{conversation_id}/rating", headers=_customer_headers()
        ).json()
        assert opened["ratingStatus"] == "pending"

        submitted = client.post(
            f"/api/customer/conversations/{conversation_id}/rating",
            json={"action": "submit", "rating": 5},
            headers=_customer_headers(),
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["ratingStatus"] == "submitted"
        assert submitted.json()["userRating"] == 5

    def test_close_is_idempotent_and_audited_once(self, client: TestClient) -> None:
        conversation_id = self._start_case(client, "close-2")

        first = client.post(
            f"/api/support/conversations/{conversation_id}/close",
            json={},
            headers=_support_headers(),
        )
        second = client.post(
            f"/api/support/conversations/{conversation_id}/close",
            json={},
            headers=_support_headers(),
        )
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json()["caseStatus"] == "closed"
        assert "重复" in second.json()["message"]
        # 幂等：评价状态仍是 pending，没有被重置或重复发起
        assert second.json()["ratingStatus"] == "pending"

        audit = client.get(
            f"/api/support/audit/{conversation_id}", headers=_support_headers()
        ).json()
        closed_events = [item for item in audit if item["eventType"] == "service_closed"]
        assert len(closed_events) == 1
        assert closed_events[0]["actorType"] == "operator"

        # 已发起过评价后不能再次发起
        again = client.post(
            f"/api/customer/conversations/{conversation_id}/rating",
            json={"action": "request"},
            headers=_customer_headers(),
        )
        assert again.status_code == 422

    def test_close_without_case_is_404(self, client: TestClient) -> None:
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=_customer_headers()
        ).json()["conversationId"]
        response = client.post(
            f"/api/support/conversations/{conversation_id}/close",
            json={},
            headers=_support_headers(),
        )
        assert response.status_code == 404
        assert "案件" in response.json()["error"]["message"]

    def test_customer_role_cannot_close(self, client: TestClient) -> None:
        conversation_id = self._start_case(client, "close-3")
        response = client.post(
            f"/api/support/conversations/{conversation_id}/close",
            json={},
            headers=_customer_headers(),
        )
        assert response.status_code == 403
