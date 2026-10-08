"""模型适配层：文本与多模态理解。

设计要点：
- `ModelProvider` 是领域层唯一依赖的接口，领域层不感知 HTTP/厂商差异；
- `OpenAICompatibleModelProvider` 走标准 `/v1/chat/completions`，可对接比赛允许的
  任意兼容服务；凭证只来自后端配置；
- `MockModelProvider` 只在 `run_mode=mock` 且显式注入时使用，返回带 `MOCK` 标记的
  固定结构，绝不冒充真实模型；
- 未配置时抛 `ProviderNotConfigured`，健康检查如实报告 `unavailable`。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.errors import (
    ProviderNotConfigured,
    ProviderRequestFailed,
    ProviderTimeout,
)


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str
    image_data_urls: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        if not self.image_data_urls:
            return {"role": self.role, "content": self.content}
        parts: list[dict[str, Any]] = [{"type": "text", "text": self.content}]
        parts.extend(
            {"type": "image_url", "image_url": {"url": url}} for url in self.image_data_urls
        )
        return {"role": self.role, "content": parts}


@dataclass(slots=True)
class ChatResult:
    text: str
    model: str
    latency_seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    is_mock: bool = False


@runtime_checkable
class ModelProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def supports_vision(self) -> bool: ...

    def available(self) -> bool: ...

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
    ) -> ChatResult: ...


class OpenAICompatibleModelProvider:
    """标准 OpenAI 兼容 Chat Completions 适配器。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        vision_model: str = "",
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._vision_model = vision_model
        self._timeout = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> OpenAICompatibleModelProvider:
        return cls(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            vision_model=settings.llm_vision_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def vision_model_id(self) -> str:
        return self._vision_model

    def configure(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        vision_model: str | None = None,
    ) -> None:
        """运行时改配置（模型配置页的保存动作）。

        只改传入的字段；`api_key` 传空字符串表示**保持原值**（页面上不回显密钥，
        留空即「不改」），传 `"-"` 表示清空。
        """

        if base_url is not None and base_url.strip():
            self._base_url = base_url.strip().rstrip("/")
        if api_key is not None:
            if api_key == "-":
                self._api_key = ""
            elif api_key.strip():
                self._api_key = api_key.strip()
        if model is not None and model.strip():
            self._model = model.strip()
        if vision_model is not None:
            self._vision_model = vision_model.strip()

    def set_active_model(self, model: str) -> None:
        """把「生效的文本模型」换成另一个（模型配置页的切换动作）。

                只改内存里的模型名：持久化由领域层写
        untime_setting，
                启动时再读回来套用（见 RuntimeContext.apply_runtime_settings）。
        """

        if not model.strip():
            raise ValueError("模型名不能为空")
        self._model = model.strip()

    @property
    def supports_vision(self) -> bool:
        return bool(self._vision_model)

    def available(self) -> bool:
        return bool(self._base_url and self._api_key and self._model)

    def list_models(self) -> list[str]:
        """列出网关上的模型 id（供「模型配置」页展示与校验）。

        失败时不抛错而是返回空列表：这个列表只是**展示与校验**用，
        拿不到不该让配置页打不开（真实的连通性由 `test_model` 负责判定）。
        """

        if not (self._base_url and self._api_key):
            return []
        request = urllib.request.Request(
            f"{self._base_url}/v1/models",
            headers={"Authorization": f"Bearer {self._api_key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=min(self._timeout, 15.0)) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception:
            return []
        items = body.get("data") if isinstance(body, dict) else None
        if not isinstance(items, list):
            return []
        return [str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")]

    def test_model(self, model: str) -> ChatResult:
        """用一次极小的真实请求验证某个模型可用（模型配置页的「测试连接」）。

        走 `complete()` 同一套路径，因此超时、HTTP 错误、未配置等都会以
        领域错误抛出，由路由转成如实的状态，而不是在本方法里吞掉。
        """

        original = self._model
        self._model = model
        try:
            return self.complete(
                [ChatMessage(role="user", content="只回复两个字：可用")],
                temperature=0.0,
                max_tokens=8,
            )
        finally:
            self._model = original

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
    ) -> ChatResult:
        if not self.available():
            raise ProviderNotConfigured(
                "文本模型未配置",
                detail="缺少 ANKER_AGENT_LLM_BASE_URL / ANKER_AGENT_LLM_API_KEY / ANKER_AGENT_LLM_MODEL",
            )

        wants_vision = any(message.image_data_urls for message in messages)
        model = self._model
        if wants_vision:
            if not self.supports_vision:
                raise ProviderNotConfigured(
                    "多模态模型未配置",
                    detail="请求包含图片，但未设置 ANKER_AGENT_LLM_VISION_MODEL",
                )
            model = self._vision_model

        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.to_payload() for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if urlparse(self._base_url).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}

        started = time.perf_counter()
        timeout = (
            min(self._timeout, timeout_seconds) if timeout_seconds is not None else self._timeout
        )
        deadline = time.monotonic() + timeout
        try:
            # Use a per-call client; do not inherit Windows' implicit loopback proxy.
            with (
                httpx.Client(timeout=timeout, trust_env=False) as client,
                client.stream(
                    "POST", f"{self._base_url}/v1/chat/completions", json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}",
                             "Accept": "application/json",
                             "User-Agent": "loreal-consumer-service/0.1"},
                ) as response,
            ):
                response.raise_for_status()
                chunks = []
                for chunk in response.iter_bytes():
                    if time.monotonic() >= deadline:
                        raise ProviderTimeout("模型请求超过总等待时间")
                    chunks.append(chunk)
                    try:
                        json.loads(b"".join(chunks).decode("utf-8"))
                        break
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        continue
                raw = b"".join(chunks)
                body = json.loads(raw.decode("utf-8"))
        except ProviderTimeout:
            raise
        except httpx.HTTPStatusError as exc:
            raise ProviderRequestFailed(
                f"模型服务返回 HTTP {exc.response.status_code}",
                detail="请核对模型服务配置和额度",
            ) from exc
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise ProviderTimeout(
                f"模型请求超时（{timeout}s）", detail="模型超时与人工等待无关"
            ) from exc
        except Exception as exc:
            raise ProviderRequestFailed(
                f"模型请求失败：{type(exc).__name__}", detail=str(exc)[:300]
            ) from exc

        latency = time.perf_counter() - started
        choices = body.get("choices") or []
        if not choices:
            raise ProviderRequestFailed("模型返回缺少 choices", detail=json.dumps(body)[:300])
        choice = choices[0]
        message = choice.get("message") or {}
        usage = body.get("usage") or {}
        return ChatResult(
            text=(message.get("content") or "").strip(),
            model=body.get("model") or model,
            latency_seconds=latency,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
        )


class MockModelProvider:
    """确定性模拟模型，仅用于测试与早期联调。

    返回内容一律带 `mock:` 前缀，便于测试断言与审查时一眼看出未接通真实模型。
    绝不在 live 模式下自动启用。
    """

    def __init__(self, *, model_id: str = "mock-model", responses: list[str] | None = None) -> None:
        self._model_id = model_id
        self._responses = list(responses or [])
        self._calls: list[list[ChatMessage]] = []

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def supports_vision(self) -> bool:
        return True

    @property
    def calls(self) -> list[list[ChatMessage]]:
        return self._calls

    def available(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        """模拟提供者只有自己一个「模型」：让模型配置页在测试环境也能渲染。"""

        return [self._model_id]

    def test_model(self, model: str) -> ChatResult:
        return self.complete([ChatMessage(role="user", content="ping")], max_tokens=8)

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
    ) -> ChatResult:
        del temperature, max_tokens, timeout_seconds
        self._calls.append(list(messages))
        if self._responses:
            text = self._responses.pop(0)
        elif json_mode:
            text = json.dumps({"mock": True, "note": "mock provider default"}, ensure_ascii=False)
        else:
            text = "mock: 这是测试用模拟回复，不代表真实模型输出。"
        return ChatResult(
            text=text,
            model=self._model_id,
            latency_seconds=0.0,
            is_mock=True,
        )
