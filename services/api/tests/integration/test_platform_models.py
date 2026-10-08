"""平台配置接口（模型配置）的集成测试。

关注点：
1. 只读配置里**绝不能出现密钥**（只给模型名与网关主机名）；
2. 角色边界：客户角色 403（这是运维视角，不是客服业务接口）；
3. 「测试连接」只允许已配置或网关确实提供的模型，不能变成任意模型名的代理；
4. 未接入的能力（重排序）如实标 `wired=false`，不伪装成可用。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.case_state.models import Base as CaseBase
from app.knowledge.models import Base as KnowledgeBase

CUSTOMER = {"X-Demo-View-Role": "customer"}
SUPPORT = {"X-Demo-View-Role": "support"}


class _StubEmbedding:
    model_id = "stub-embedding"
    dimension = 1024

    def available(self) -> bool:
        return True

    def describe(self) -> dict[str, str]:
        return {"backend": "stub", "model_id": self.model_id}

    def encode(self, texts: list[str], *, is_query: bool = False) -> Any:
        return [[0.0] * 1024 for _ in texts]


class _StubProvider:
    """声明支持视觉、能列模型、能按名字测试的桩提供者。"""

    def __init__(self, models: list[str], fail_for: set[str] | None = None) -> None:
        self._models = models
        self._fail_for = fail_for or set()
        self.tested: list[str] = []
        self.messages: list[Any] = []
        #: 累计每一轮的所有消息：现在一轮会有「理解 + 回复」两次模型调用
        self.all_messages: list[Any] = []
        #: 记录 `configure()` 收到的参数，供「分能力配置」用例断言真的传到了提供者
        self.configured: list[dict[str, Any]] = []
        self.base_url = "https://gateway.example.com/v1"

    def configure(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        vision_model: str | None = None,
    ) -> None:
        """运行时改配置。真实提供者会重建 httpx 客户端，这里只记录并切换模型。"""

        self.configured.append(
            {
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
                "vision_model": vision_model,
            }
        )
        if base_url:
            self.base_url = base_url
        if model:
            self.set_active_model(model)

    @property
    def model_id(self) -> str:
        return self._models[0]

    @property
    def supports_vision(self) -> bool:
        return True

    def available(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return list(self._models)

    def set_active_model(self, model: str) -> None:
        self._models = [model, *[m for m in self._models if m != model]]

    def test_model(self, model: str) -> Any:
        from app.errors import ProviderRequestFailed
        from app.integrations.model_provider import ChatResult

        self.tested.append(model)
        if model in self._fail_for:
            raise ProviderRequestFailed("模型服务返回 HTTP 400", detail="不支持的模型")
        return ChatResult(text="可用", model=model, latency_seconds=0.02)

    def complete(self, messages: list[Any], **_: Any) -> Any:
        """记录收到的消息并返回一份可解析的理解结果（供「模板是否生效」用例断言）。"""

        import json

        from app.integrations.model_provider import ChatResult

        self.messages = list(messages)
        self.all_messages.extend(messages)
        payload = {
            "product_model_text": "",
            "fault_type": "unknown",
            "fault_part": "unknown",
            "phenomenon": "客户描述问题",
            "intents": ["diagnosis"],
            "emotion_level": "calm",
            "complaint_risk": "not_flagged",
            "complaint_reason": "",
            "country_code_text": "",
            "purchase_channel": "unknown",
            "seller_name_raw": "",
            "image_visible_clues": [],
            "urgency_note": "",
        }
        return ChatResult(
            text=json.dumps(payload, ensure_ascii=False), model=self.model_id, latency_seconds=0.0
        )


@pytest.fixture
def client(tmp_path: Path) -> Iterator[tuple[TestClient, _StubProvider]]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.main import create_app
    from app.runtime import RuntimeContext
    from app.tools.registry import build_default_registry

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'p.sqlite3'}", future=True)
    # 平台表（runtime_setting / prompt_template）声明在 CaseBase 上，
    # 但**必须先导入模块**才会注册到 metadata——不导入就建不出表（与缺陷第 39 项同源的坑）。
    from app.domain.platform import models as _platform_models  # noqa: F401

    CaseBase.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    provider = _StubProvider(["stub-chat", "stub-vision"], fail_for={"stub-vision"})
    settings = Settings(
        runtime_dir=str(tmp_path / "runtime"),
        llm_base_url="https://gateway.example.com/v1",
        llm_api_key="sk-should-never-leak",
        llm_model="stub-chat",
        llm_vision_model="stub-vision",
    )
    context = RuntimeContext(
        settings=settings,
        engine=engine,
        session_factory=factory,
        model_provider=provider,
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
        yield test_client, provider
    engine.dispose()


def test_model_config_lists_providers_without_secrets(
    client: tuple[TestClient, _StubProvider],
) -> None:
    test_client, _provider = client
    response = test_client.get("/api/platform/models", headers=SUPPORT)
    assert response.status_code == 200
    body = response.json()

    assert body["gatewayHost"] == "gateway.example.com"
    assert body["availableModels"] == ["stub-chat", "stub-vision"]

    keys = {item["key"]: item for item in body["providers"]}
    assert keys["llm"]["model"] == "stub-chat"
    assert keys["vision"]["state"] == "ready"
    assert keys["rerank"]["wired"] is False
    assert "未配置重排序服务" in keys["rerank"]["detail"]

    # 密钥绝不能出现在响应体里
    raw = response.text
    assert "sk-should-never-leak" not in raw
    assert "api_key" not in raw.lower()


def test_model_config_requires_support_role(client: tuple[TestClient, _StubProvider]) -> None:
    test_client, _provider = client
    assert test_client.get("/api/platform/models", headers=CUSTOMER).status_code == 403


def test_test_model_reports_success(
    client: tuple[TestClient, _StubProvider],
) -> None:
    test_client, provider = client
    response = test_client.post(
        "/api/platform/models/test", json={"model": "stub-chat"}, headers=SUPPORT
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["latencySeconds"] >= 0
    assert body["message"].startswith("连通")
    assert provider.tested == ["stub-chat"]


def test_test_model_reports_failure_honestly(
    client: tuple[TestClient, _StubProvider],
) -> None:
    test_client, _provider = client
    response = test_client.post(
        "/api/platform/models/test", json={"model": "stub-vision"}, headers=SUPPORT
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "ProviderRequestFailed" in body["message"]


def test_test_model_rejects_arbitrary_model(client: tuple[TestClient, _StubProvider]) -> None:
    """不能拿这个接口当任意模型名的代理去试探未授权模型。"""

    test_client, provider = client
    response = test_client.post(
        "/api/platform/models/test", json={"model": "gpt-4o-someone-elses"}, headers=SUPPORT
    )
    assert response.status_code == 422
    assert provider.tested == []


def test_test_model_requires_support_role(client: tuple[TestClient, _StubProvider]) -> None:
    test_client, _provider = client
    response = test_client.post(
        "/api/platform/models/test", json={"model": "stub-chat"}, headers=CUSTOMER
    )
    assert response.status_code == 403


def test_switch_active_model_persists_and_applies(
    client: tuple[TestClient, _StubProvider],
) -> None:
    """切换生效模型：内存立即生效 + 持久化（重启后由启动流程套用）。"""

    test_client, provider = client
    response = test_client.post(
        "/api/platform/models/active", json={"model": "stub-vision"}, headers=SUPPORT
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"] == "stub-vision"
    assert body["persisted"] is True
    # 立即生效：提供者的 model_id 已经变了
    assert provider.model_id == "stub-vision"


def test_switch_active_model_rejects_unknown_model(
    client: tuple[TestClient, _StubProvider],
) -> None:
    """不允许切到网关没有的模型：否则之后所有对话都会失败，比不让切更糟。"""

    test_client, provider = client
    before = provider.model_id
    response = test_client.post(
        "/api/platform/models/active", json={"model": "not-a-real-model"}, headers=SUPPORT
    )
    assert response.status_code == 422
    assert provider.model_id == before


def test_switch_active_model_requires_support_role(
    client: tuple[TestClient, _StubProvider],
) -> None:
    test_client, _provider = client
    response = test_client.post(
        "/api/platform/models/active", json={"model": "stub-chat"}, headers=CUSTOMER
    )
    assert response.status_code == 403


class TestPerCapabilityConfig:
    """分能力配置：每一行「配置」写入的设置真的落库、真的生效（DEV-031）。"""

    def test_save_llm_config_applies_immediately_and_masks_key(
        self, client: tuple[TestClient, _StubProvider]
    ) -> None:
        test_client, provider = client
        response = test_client.put(
            "/api/platform/models/config",
            json={
                "baseUrl": "https://gateway2.example.com/v1",
                "apiKey": "sk-a-brand-new-secret",
                "model": "stub-chat",
            },
            headers=SUPPORT,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        # 立即生效：参数确实传给了提供者
        assert provider.configured[-1]["base_url"] == "https://gateway2.example.com/v1"
        assert provider.base_url == "https://gateway2.example.com/v1"
        # 密钥只进不出：响应体里不能出现原文，只给掩码与「是否已配置」
        assert "sk-a-brand-new-secret" not in response.text
        assert body["config"]["hasApiKey"] is True
        assert body["config"]["apiKeyMasked"].endswith("cret")
        assert body["config"]["textModel"] == "stub-chat"

    def test_save_embedding_model_persists_and_hints_restart(
        self, client: tuple[TestClient, _StubProvider]
    ) -> None:
        """向量模型改动写库，并**如实**说明需要重启才生效（本地 ONNX 不能热替换）。

        关键点：保存后接口**不能**把新模型报成「已生效」——运行中的编码器还是旧的那个，
        因此这里同时断言「页面看到的仍是当前生效值」与「启动路径会套用新值」。
        """

        test_client, _provider = client
        runtime = test_client.app.state.runtime
        effective_before = runtime.settings.embedding_model_id

        response = test_client.put(
            "/api/platform/models/config",
            json={"embeddingModel": "BAAI/bge-small-zh-v1.5", "embeddingPath": "./models/bge-m3"},
            headers=SUPPORT,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert "需重启后端生效" in body["message"]
        # 不谎报：未重启前仍显示当前真正生效的编码模型
        assert body["config"]["embeddingModel"] == effective_before

        # 已落库（下一次启动会读它）
        from app.domain.platform.settings import (
            EMBEDDING_MODEL_KEY,
            EMBEDDING_PATH_KEY,
            get_setting,
        )

        with runtime.session_factory() as session:
            assert get_setting(session, EMBEDDING_MODEL_KEY) == "BAAI/bge-small-zh-v1.5"
            assert get_setting(session, EMBEDDING_PATH_KEY) == "./models/bge-m3"

        # 启动路径（`build_runtime` 用的同一段代码）确实会套用保存值
        from app.runtime import _apply_saved_embedding_settings

        probe = Settings(
            runtime_dir=str(runtime.settings.runtime_path),
            embedding_model_id="BAAI/bge-m3",
        )
        _apply_saved_embedding_settings(probe, runtime.session_factory)
        assert probe.embedding_model_id == "BAAI/bge-small-zh-v1.5"
        assert probe.embedding_model_path == "./models/bge-m3"

    def test_save_config_keeps_masked_key_when_field_is_blank(
        self, client: tuple[TestClient, _StubProvider]
    ) -> None:
        """页面回填的是掩码：留空表示不改，不能把掩码写进密钥字段。"""

        test_client, _provider = client
        first = test_client.put(
            "/api/platform/models/config",
            json={"apiKey": "sk-keep-this-key"},
            headers=SUPPORT,
        )
        assert first.status_code == 200
        blank = test_client.put(
            "/api/platform/models/config",
            json={"apiKey": "", "model": "stub-chat"},
            headers=SUPPORT,
        )
        assert blank.status_code == 200, blank.text
        assert blank.json()["config"]["hasApiKey"] is True
        assert "sk-keep-this-key" not in blank.text

    def test_save_config_reports_connectivity_failure_honestly(
        self, client: tuple[TestClient, _StubProvider]
    ) -> None:
        """保存后必须真的测一次：测不通就如实回 `ok=false`，不能只说「已保存」。"""

        test_client, provider = client
        response = test_client.put(
            "/api/platform/models/config",
            json={"model": "stub-vision"},  # 桩里这个模型会失败
            headers=SUPPORT,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is False
        assert "测试失败" in body["message"]
        assert "ProviderRequestFailed" in body["message"]
        # 失败也要留下已保存的配置（否则用户改不回可用模型）
        assert provider.model_id == "stub-vision"

    def test_save_config_requires_support_role(
        self, client: tuple[TestClient, _StubProvider]
    ) -> None:
        test_client, _provider = client
        response = test_client.put(
            "/api/platform/models/config", json={"model": "stub-chat"}, headers=CUSTOMER
        )
        assert response.status_code == 403


class TestPromptTemplates:
    """模板表：内置模板会被播种；新增默认停用；编辑递增版本；可启停。"""

    def test_builtin_templates_are_seeded(self, client: tuple[TestClient, _StubProvider]) -> None:
        test_client, _provider = client
        response = test_client.get("/api/platform/prompt-templates", headers=SUPPORT)
        assert response.status_code == 200
        rows = response.json()
        codes = {row["code"] for row in rows}
        assert {"LOREAL_AUTO_REPLY", "LOREAL_ASSISTANT", "LOREAL_SAFETY"} <= codes
        assistant = next(row for row in rows if row["code"] == "LOREAL_ASSISTANT")
        assert assistant["isBuiltin"] is True
        assert assistant["status"] == "enabled"
        assert assistant["revision"] == 1
        assert "欧莱雅美妆电商客服工作台" in assistant["content"]

    def test_create_update_and_toggle(self, client: tuple[TestClient, _StubProvider]) -> None:
        test_client, _provider = client
        created = test_client.post(
            "/api/platform/prompt-templates",
            json={
                "code": "custom_reply",
                "name": "自定义回复风格",
                "scenario": "实验用",
                "content": "你是客服，请用一句话回复。",
            },
            headers=SUPPORT,
        )
        assert created.status_code == 200, created.text
        row = created.json()
        template_id = row["templateId"]
        # 新模板默认停用：改模型行为必须是显式动作
        assert row["status"] == "disabled"
        assert row["isBuiltin"] is False

        updated = test_client.put(
            f"/api/platform/prompt-templates/{template_id}",
            json={"content": "你是客服，请用两句话回复，不要承诺赔付。"},
            headers=SUPPORT,
        )
        assert updated.status_code == 200
        assert updated.json()["revision"] == 2

        enabled = test_client.post(
            f"/api/platform/prompt-templates/{template_id}/status",
            json={"status": "enabled"},
            headers=SUPPORT,
        )
        assert enabled.status_code == 200
        assert enabled.json()["status"] == "enabled"

        disabled = test_client.post(
            f"/api/platform/prompt-templates/{template_id}/status",
            json={"status": "disabled"},
            headers=SUPPORT,
        )
        assert disabled.json()["status"] == "disabled"

    def test_duplicate_code_is_rejected(self, client: tuple[TestClient, _StubProvider]) -> None:
        test_client, _provider = client
        response = test_client.post(
            "/api/platform/prompt-templates",
            json={"code": "LOREAL_ASSISTANT", "name": "重复", "content": "x"},
            headers=SUPPORT,
        )
        assert response.status_code == 422

    def test_unknown_template_and_bad_status(
        self, client: tuple[TestClient, _StubProvider]
    ) -> None:
        test_client, _provider = client
        assert (
            test_client.put(
                "/api/platform/prompt-templates/ptpl-missing",
                json={"content": "x"},
                headers=SUPPORT,
            ).status_code
            == 404
        )
        rows = test_client.get("/api/platform/prompt-templates", headers=SUPPORT).json()
        template_id = rows[0]["templateId"]
        assert (
            test_client.post(
                f"/api/platform/prompt-templates/{template_id}/status",
                json={"status": "paused"},
                headers=SUPPORT,
            ).status_code
            == 422
        )


def test_prompt_templates_require_support_role(
    client: tuple[TestClient, _StubProvider],
) -> None:
    test_client, _provider = client
    assert test_client.get("/api/platform/prompt-templates", headers=CUSTOMER).status_code == 403


def test_switch_back_to_configured_model_not_listed_by_gateway(
    client: tuple[TestClient, _StubProvider],
) -> None:
    """真实踩到的坑：网关 /v1/models 只列了部分模型，已配置的模型不在里面。

    实测 deepseek-chat 能正常调用但不在网关列表里——如果切换只认列表，
    切走之后就**再也切不回来**。因此允许范围必须是「网关列表 ∪ 已配置模型」。
    """

    test_client, provider = client
    listed = set(provider.list_models())
    assert "stub-vision" in listed

    # 造一个「已配置但网关不返回」的模型：改 settings 后重开一次应用
    # 这里用最直接的方式验证规则：把网关列表清空，已配置模型仍应可切。
    provider._models = []
    response = test_client.post(
        "/api/platform/models/active", json={"model": "stub-chat"}, headers=SUPPORT
    )
    assert response.status_code == 200, response.text
    assert response.json()["model"] == "stub-chat"
