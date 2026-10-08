"""模型与编码适配器测试。

关注点：
- 未配置时必须抛 ProviderNotConfigured，不能静默返回固定回复；
- mock 提供方必须带明确标记，且不能在 live 模式下被自动启用；
- 编码后端在 live + mock 配置组合下必须被拒绝。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.errors import ProviderNotConfigured
from app.integrations.embedding_provider import (
    MockEmbeddingProvider,
    build_embedding_provider,
)
from app.integrations.model_provider import (
    ChatMessage,
    MockModelProvider,
    OpenAICompatibleModelProvider,
)


def _settings(**overrides: object) -> Settings:
    base = {
        "llm_base_url": "",
        "llm_api_key": "",
        "llm_model": "",
        "llm_vision_model": "",
        "embedding_backend": "onnx-local",
        "run_mode": "live",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestOpenAICompatibleProvider:
    def test_deepseek_requests_use_direct_answer_mode(self, monkeypatch):
        original = httpx.Client

        def handle(request):
            payload = json.loads(request.content)
            assert payload["thinking"] == {"type": "disabled"}
            return httpx.Response(200, json={
                "model": "deepseek-flash",
                "choices": [{"message": {"content": "收到"}}],
            })

        monkeypatch.setattr(
            "app.integrations.model_provider.httpx.Client",
            lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
        )
        provider = OpenAICompatibleModelProvider(
            base_url="https://api.deepseek.com", api_key="fixture-key", model="deepseek-chat",
        )
        assert provider.complete([ChatMessage(role="user", content="你好")]).text == "收到"

    def test_http_transport_sends_json_and_reads_token_usage(self, monkeypatch):
        original = httpx.Client

        def handle(request):
            payload = json.loads(request.content)
            assert payload["model"] == "text-model"
            assert payload["stream"] is False
            assert request.headers["accept"] == "application/json"
            return httpx.Response(200, json={
                "model": "text-model",
                "choices": [{"message": {"content": "收到"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 2},
            })

        monkeypatch.setattr(
            "app.integrations.model_provider.httpx.Client",
            lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
        )
        provider = OpenAICompatibleModelProvider(
            base_url="https://example.invalid", api_key="not-a-real-key", model="text-model",
        )
        result = provider.complete([ChatMessage(role="user", content="你好")], timeout_seconds=10)
        assert result.text == "收到"
        assert (result.prompt_tokens, result.completion_tokens) == (9, 2)
        assert not result.is_mock

    def test_unconfigured_provider_is_unavailable(self) -> None:
        provider = OpenAICompatibleModelProvider.from_settings(_settings())
        assert provider.available() is False
        with pytest.raises(ProviderNotConfigured, match="文本模型未配置"):
            provider.complete([ChatMessage(role="user", content="你好")])

    def test_vision_requires_separate_model(self) -> None:
        provider = OpenAICompatibleModelProvider.from_settings(
            _settings(
                llm_base_url="https://example.invalid",
                llm_api_key="not-a-real-key",
                llm_model="text-model",
            )
        )
        assert provider.available() is True
        assert provider.supports_vision is False
        with pytest.raises(ProviderNotConfigured, match="多模态模型未配置"):
            provider.complete(
                [
                    ChatMessage(
                        role="user",
                        content="看看这张图",
                        image_data_urls=["data:image/png;base64,AAAA"],
                    )
                ]
            )

    def test_message_payload_shape(self) -> None:
        text_message = ChatMessage(role="user", content="只有文字")
        assert text_message.to_payload() == {"role": "user", "content": "只有文字"}

        vision_message = ChatMessage(
            role="user", content="描述图片", image_data_urls=["data:image/png;base64,AAAA"]
        )
        payload = vision_message.to_payload()
        assert isinstance(payload["content"], list)
        assert payload["content"][0] == {"type": "text", "text": "描述图片"}
        assert payload["content"][1]["type"] == "image_url"


class TestMockProvider:
    def test_mock_output_is_clearly_marked(self) -> None:
        provider = MockModelProvider()
        result = provider.complete([ChatMessage(role="user", content="你好")])
        assert result.is_mock is True
        assert result.text.startswith("mock:")

    def test_mock_records_calls_without_network(self) -> None:
        provider = MockModelProvider(responses=["第一次", "第二次"])
        provider.complete([ChatMessage(role="user", content="a")])
        provider.complete([ChatMessage(role="user", content="b")])
        assert len(provider.calls) == 2
        assert provider.calls[0][0].content == "a"


class TestEmbeddingProviderSelection:
    def test_mock_requires_explicit_reason(self) -> None:
        with pytest.raises(ValueError, match="必须说明使用理由"):
            MockEmbeddingProvider()

    def test_mock_produces_dense_and_sparse(self) -> None:
        provider = MockEmbeddingProvider(dimension=16, reason="单元测试")
        batch = provider.encode(["吸尘器吸力弱", "滤网堵塞"])
        assert batch.dimension == 16
        assert len(batch.dense) == 2
        assert all(len(item.indices) > 0 for item in batch.sparse)
        assert batch.is_mock is True

    def test_live_mode_rejects_mock_backend(self) -> None:
        settings = _settings(run_mode="live", embedding_backend="mock")
        with pytest.raises(ProviderNotConfigured, match="live 模式不允许 mock 编码后端"):
            build_embedding_provider(settings)

    def test_mock_backend_allowed_in_mock_mode(self) -> None:
        settings = _settings(run_mode="mock", embedding_backend="mock")
        provider = build_embedding_provider(settings)
        assert provider.available() is True
        assert provider.describe()["backend"] == "mock"

    def test_empty_input_is_rejected(self) -> None:
        from app.errors import ProviderRequestFailed

        provider = MockEmbeddingProvider(reason="单元测试")
        with pytest.raises(ProviderRequestFailed, match="编码输入为空"):
            provider.encode([])
