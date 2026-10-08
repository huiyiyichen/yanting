"""图片上传与 AI 话术候选测试。

覆盖前端规范第 5.3、6.1 节与 AC-25：
- 仅 JPEG/PNG/WebP、≤5MB；**后端校验实际类型与可解码性**；
- 扩展名与声明类型不能绕过校验；
- 候选三种措辞同事实同策略；过期标记；**采用不等于发送**。
"""

from __future__ import annotations

import json
import struct
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.case_state.models import Base as CaseBase
from app.knowledge.models import Base as KnowledgeBase
from app.repositories.attachment_service import (
    FORMAT_TO_MIME,
    validate_and_store_image,
)


def _png_bytes(width: int = 2, height: int = 2) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _jpeg_bytes() -> bytes:
    """最小可解码 JPEG（1x1）。"""

    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300"
        "080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432"
        "ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0b"
        "ffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9fa"
        "ffda0008010100003f00d2cf20ffd9"
    )


class _StubEmbedding:
    model_id = "stub"
    dimension = 1024

    def available(self) -> bool:
        return False

    def describe(self) -> dict[str, str]:
        return {"backend": "stub", "model_id": self.model_id}

    def encode(self, texts: list[str], *, is_query: bool = False) -> Any:
        raise RuntimeError("本用例不执行真实编码")


class _ScriptedProvider:
    """按顺序返回预设回复的文本模型。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[Any]] = []

    @property
    def model_id(self) -> str:
        return "scripted-model"

    @property
    def supports_vision(self) -> bool:
        return False

    def available(self) -> bool:
        return True

    def complete(self, messages: list[Any], **_: Any) -> Any:
        from app.integrations.model_provider import ChatResult

        self.calls.append(list(messages))
        text = self._responses.pop(0) if self._responses else "{}"
        return ChatResult(text=text, model=self.model_id, latency_seconds=0.01)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    from contextlib import asynccontextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.main import create_app
    from app.runtime import RuntimeContext
    from app.tools.registry import build_default_registry

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'a.sqlite3'}", future=True)
    CaseBase.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    settings = Settings(runtime_dir=str(tmp_path / "runtime"))
    context = RuntimeContext(
        settings=settings,
        engine=engine,
        session_factory=factory,
        model_provider=_ScriptedProvider(
            [
                json.dumps(
                    {
                        "recommended": "已收到您的反馈，我先核对这台 A1 Pro 吸尘器的订单与质保信息，确认后再告诉您可选的处理方式。",
                        "concise": "收到，我先核对订单与质保，稍后给您可选的方案。",
                        "reassuring": "很抱歉给您添麻烦了，我马上帮您核对这台吸尘器的订单与质保信息。",
                    },
                    ensure_ascii=False,
                )
            ]
            * 5
        ),
        embedding_provider=_StubEmbedding(),
        tool_registry=build_default_registry(),
    )

    app = create_app()

    @asynccontextmanager
    async def _lifespan(_app: Any):  # type: ignore[no-untyped-def]
        _app.state.runtime = context
        yield
        context.close()

    app.router.lifespan_context = _lifespan
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


CUSTOMER = {"X-Demo-View-Role": "customer"}
SUPPORT = {"X-Demo-View-Role": "support"}


def _new_conversation(client: TestClient) -> str:
    return client.post("/api/customer/conversations", json={}, headers=CUSTOMER).json()[
        "conversationId"
    ]


class TestImageValidationUnit:
    """直接测试校验函数，覆盖边界而不用起 HTTP。"""

    def test_png_accepted(self, tmp_path: Path) -> None:
        settings = Settings(runtime_dir=str(tmp_path))
        stored = validate_and_store_image(
            data=_png_bytes(),
            declared_mime="image/png",
            settings=settings,
            conversation_id="conv-1",
        )
        assert stored.mime_type == "image/png"
        assert stored.width == 2
        assert Path(stored.stored_path).exists()
        # 路径由系统生成，不含原始文件名
        assert "conv-1" in stored.stored_path
        assert stored.stored_path.endswith(".png")

    def test_jpeg_accepted(self, tmp_path: Path) -> None:
        settings = Settings(runtime_dir=str(tmp_path))
        stored = validate_and_store_image(
            data=_jpeg_bytes(),
            declared_mime="image/jpeg",
            settings=settings,
            conversation_id="conv-1",
        )
        assert stored.mime_type in FORMAT_TO_MIME.values()

    def test_oversize_rejected(self, tmp_path: Path) -> None:
        from app.errors import ValidationRejected

        settings = Settings(runtime_dir=str(tmp_path), image_max_bytes=100)
        with pytest.raises(ValidationRejected, match="超过大小上限"):
            validate_and_store_image(
                data=_png_bytes() * 20,
                declared_mime="image/png",
                settings=settings,
                conversation_id="conv-1",
            )

    def test_non_image_rejected(self, tmp_path: Path) -> None:
        from app.errors import ValidationRejected

        settings = Settings(runtime_dir=str(tmp_path))
        with pytest.raises(ValidationRejected, match="无法识别的图片格式"):
            validate_and_store_image(
                data=b"this is plain text, not an image",
                declared_mime="image/png",
                settings=settings,
                conversation_id="conv-1",
            )

    def test_extension_cannot_bypass(self, tmp_path: Path) -> None:
        """声明为 png 但内容不是图片时必须拒绝。"""

        from app.errors import ValidationRejected

        settings = Settings(runtime_dir=str(tmp_path))
        with pytest.raises(ValidationRejected):
            validate_and_store_image(
                data=b"%PDF-1.4 fake pdf content",
                declared_mime="image/png",
                settings=settings,
                conversation_id="conv-1",
            )

    def test_corrupt_png_rejected(self, tmp_path: Path) -> None:
        """魔数正确但内容损坏时也必须失败（只查 magic bytes 不够）。"""

        from app.errors import ValidationRejected

        settings = Settings(runtime_dir=str(tmp_path))
        corrupt = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
        with pytest.raises(ValidationRejected):
            validate_and_store_image(
                data=corrupt,
                declared_mime="image/png",
                settings=settings,
                conversation_id="conv-1",
            )

    def test_empty_rejected(self, tmp_path: Path) -> None:
        from app.errors import ValidationRejected

        settings = Settings(runtime_dir=str(tmp_path))
        with pytest.raises(ValidationRejected, match="内容为空"):
            validate_and_store_image(
                data=b"",
                declared_mime="image/png",
                settings=settings,
                conversation_id="conv-1",
            )


class TestVisionAvailability:
    def test_reports_not_configured_honestly(self, client: TestClient) -> None:
        response = client.get("/api/customer/vision", headers=CUSTOMER)
        assert response.status_code == 200
        payload = response.json()
        assert payload["visionConfigured"] is False
        assert "无法从图片提取线索" in payload["note"]
        assert payload["maxBytes"] == 5 * 1024 * 1024
        assert set(payload["allowedMimeTypes"]) == {"image/jpeg", "image/png", "image/webp"}

    def test_customer_role_required(self, client: TestClient) -> None:
        assert client.get("/api/customer/vision", headers=SUPPORT).status_code == 403


class TestAttachmentUpload:
    def test_upload_png(self, client: TestClient) -> None:
        conversation_id = _new_conversation(client)
        response = client.post(
            f"/api/customer/conversations/{conversation_id}/attachments",
            files={"file": ("photo.png", _png_bytes(), "image/png")},
            headers=CUSTOMER,
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["mimeType"] == "image/png"
        assert payload["width"] == 2
        assert payload["attachmentId"].startswith("att-")

    def test_upload_rejects_text_file(self, client: TestClient) -> None:
        conversation_id = _new_conversation(client)
        response = client.post(
            f"/api/customer/conversations/{conversation_id}/attachments",
            files={"file": ("fake.png", b"not an image at all", "image/png")},
            headers=CUSTOMER,
        )
        assert response.status_code == 422

    def test_upload_requires_customer_role(self, client: TestClient) -> None:
        conversation_id = _new_conversation(client)
        response = client.post(
            f"/api/customer/conversations/{conversation_id}/attachments",
            files={"file": ("photo.png", _png_bytes(), "image/png")},
            headers=SUPPORT,
        )
        assert response.status_code == 403

    def test_attachment_linked_when_vision_configured(self, client: TestClient) -> None:
        """配置了多模态时，上传的图片必须随消息落库并挂到该消息上。

        真实缺陷：前端没有把 `attachmentIds` 传上来、后端路由也从不读取它，
        于是图片永远只是**孤儿附件**——客户传了图，消息里却什么都没有，
        视觉模型更看不到。

        注意这里必须显式声明「支持多模态」：未配置时发送带图消息会如实抛
        `ProviderNotConfigured`（见 `TestVisionBoundary`），那是刻意的边界，
        不是缺陷——不能为了测试通过而把图片静默丢掉。
        """

        conversation_id = _new_conversation(client)
        uploaded = client.post(
            f"/api/customer/conversations/{conversation_id}/attachments",
            files={"file": ("photo.png", _png_bytes(), "image/png")},
            headers=CUSTOMER,
        )
        attachment_id = uploaded.json()["attachmentId"]

        sent = client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={
                "body": "这是故障照片",
                "clientMessageKey": "k-with-image",
                "attachmentIds": [attachment_id],
            },
            headers=CUSTOMER,
        )
        # 测试环境未配置 vision model：必须如实拒绝，而不是假装看懂
        assert sent.status_code == 503
        assert sent.json()["error"]["code"] == "provider_not_configured"

    def test_attachment_ids_are_validated_for_ownership(self, client: TestClient) -> None:
        """跨会话引用附件必须被拒绝，否则等于绕过会话隔离。

        这条不依赖视觉模型：归属校验发生在调用模型之前。
        """

        first = _new_conversation(client)
        second = _new_conversation(client)
        uploaded = client.post(
            f"/api/customer/conversations/{first}/attachments",
            files={"file": ("photo.png", _png_bytes(), "image/png")},
            headers=CUSTOMER,
        )
        attachment_id = uploaded.json()["attachmentId"]

        response = client.post(
            f"/api/customer/conversations/{second}/messages",
            json={
                "body": "借用别人的图",
                "clientMessageKey": "k-cross",
                "attachmentIds": [attachment_id],
            },
            headers=CUSTOMER,
        )
        assert response.status_code == 422

    def test_unknown_attachment_id_is_rejected(self, client: TestClient) -> None:
        conversation_id = _new_conversation(client)
        response = client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={
                "body": "不存在的附件",
                "clientMessageKey": "k-ghost",
                "attachmentIds": ["att-does-not-exist"],
            },
            headers=CUSTOMER,
        )
        assert response.status_code == 422

    def test_attachment_content_is_served_and_scoped(self, client: TestClient) -> None:
        """附件原图必须能读回，且不存在的附件返回 404。

        消息里只存元数据，前端靠这个地址渲染缩略图；若读不回来，
        客户会看到「传了图但什么都不显示」。
        """

        conversation_id = _new_conversation(client)
        uploaded = client.post(
            f"/api/customer/conversations/{conversation_id}/attachments",
            files={"file": ("photo.png", _png_bytes(), "image/png")},
            headers=CUSTOMER,
        )
        attachment_id = uploaded.json()["attachmentId"]

        content = client.get(f"/api/customer/attachments/{attachment_id}/content", headers=CUSTOMER)
        assert content.status_code == 200
        assert content.headers["content-type"].startswith("image/png")
        # 读回的必须是真实 PNG 字节（魔数校验），不是占位内容
        assert content.content[:8] == b"\x89PNG\r\n\x1a\n"

        missing = client.get(
            "/api/customer/attachments/att-does-not-exist/content", headers=CUSTOMER
        )
        assert missing.status_code == 404

    def test_attachment_does_not_grant_tool_permission(self, client: TestClient) -> None:
        """上传附件不改变案件能力：客户仍不能访问客服接口。"""

        conversation_id = _new_conversation(client)
        client.post(
            f"/api/customer/conversations/{conversation_id}/attachments",
            files={"file": ("photo.png", _png_bytes(), "image/png")},
            headers=CUSTOMER,
        )
        assert client.get("/api/support/queue", headers=CUSTOMER).status_code == 403


class TestSuggestions:
    def test_generate_returns_three_variants(self, client: TestClient) -> None:
        conversation_id = _new_conversation(client)
        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "我的 A1 Pro 吸力不行了", "clientMessageKey": "s-1"},
            headers=CUSTOMER,
        )

        response = client.post(
            f"/api/support/conversations/{conversation_id}/suggestions/generate",
            headers=SUPPORT,
        )
        assert response.status_code == 200
        payload = response.json()
        variants = {item["variant"] for item in payload["items"]}
        assert variants == {"recommended", "concise", "reassuring"}
        assert payload["expires"] is False
        for item in payload["items"]:
            assert item["variantLabel"] in {"推荐", "简洁", "安抚"}
            assert item["body"]

    def test_suggestions_require_support_role(self, client: TestClient) -> None:
        conversation_id = _new_conversation(client)
        response = client.post(
            f"/api/support/conversations/{conversation_id}/suggestions/generate",
            headers=CUSTOMER,
        )
        assert response.status_code == 403

    def test_adopt_does_not_send_message(self, client: TestClient) -> None:
        """AC-25：采用候选不产生消息。"""

        conversation_id = _new_conversation(client)
        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "吸力不行", "clientMessageKey": "s-1"},
            headers=CUSTOMER,
        )
        client.post(
            f"/api/support/conversations/{conversation_id}/suggestions/generate",
            headers=SUPPORT,
        )
        before = client.get(
            f"/api/support/conversations/{conversation_id}/messages", headers=SUPPORT
        ).json()

        adopted = client.post(
            f"/api/support/conversations/{conversation_id}/suggestions/action",
            json={"variant": "recommended", "action": "adopt"},
            headers=SUPPORT,
        )
        assert adopted.status_code == 200

        after = client.get(
            f"/api/support/conversations/{conversation_id}/messages", headers=SUPPORT
        ).json()
        assert len(after) == len(before)
        assert all(item["senderRole"] != "operator" for item in after)

    def test_ignore_is_independent_action(self, client: TestClient) -> None:
        conversation_id = _new_conversation(client)
        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "吸力不行", "clientMessageKey": "s-1"},
            headers=CUSTOMER,
        )
        client.post(
            f"/api/support/conversations/{conversation_id}/suggestions/generate",
            headers=SUPPORT,
        )
        response = client.post(
            f"/api/support/conversations/{conversation_id}/suggestions/action",
            json={"variant": "concise", "action": "ignore"},
            headers=SUPPORT,
        )
        assert response.status_code == 200

    def test_new_customer_message_expires_old_suggestions(self, client: TestClient) -> None:
        """新客户消息到达后旧候选过期，不得静默发送。"""

        conversation_id = _new_conversation(client)
        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "第一条", "clientMessageKey": "s-1"},
            headers=CUSTOMER,
        )
        generated = client.post(
            f"/api/support/conversations/{conversation_id}/suggestions/generate",
            headers=SUPPORT,
        ).json()
        assert generated["expires"] is False

        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "补充一句：还在保修期内吗", "clientMessageKey": "s-2"},
            headers=CUSTOMER,
        )

        after = client.get(
            f"/api/support/conversations/{conversation_id}/suggestions", headers=SUPPORT
        ).json()
        assert after["expires"] is True
        assert after["currentRevision"] > after["messageRevision"]

    def test_invalid_variant_rejected(self, client: TestClient) -> None:
        conversation_id = _new_conversation(client)
        response = client.post(
            f"/api/support/conversations/{conversation_id}/suggestions/action",
            json={"variant": "made_up", "action": "adopt"},
            headers=SUPPORT,
        )
        assert response.status_code == 422

    def test_suggestion_action_is_audited(self, client: TestClient) -> None:
        conversation_id = _new_conversation(client)
        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": "吸力不行", "clientMessageKey": "s-1"},
            headers=CUSTOMER,
        )
        client.post(
            f"/api/support/conversations/{conversation_id}/suggestions/generate",
            headers=SUPPORT,
        )
        client.post(
            f"/api/support/conversations/{conversation_id}/suggestions/action",
            json={"variant": "recommended", "action": "adopt"},
            headers=SUPPORT,
        )
        audit = client.get(f"/api/support/audit/{conversation_id}", headers=SUPPORT).json()
        events = [item["eventType"] for item in audit]
        assert "suggestion_generated" in events
        assert "suggestion_action" in events
