"""运行状态与外部能力实测。

`/api/health` 只读本地配置与路径，不发起外部请求；
`/api/health/probe` 主动调用一次真实模型与编码，用于 S0 的"未接通能力真实记录"。
两者都不返回任何密钥。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

from app.integrations.embedding_provider import EmbeddingProvider
from app.integrations.model_provider import ChatMessage, ModelProvider
from app.runtime import RuntimeContext
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/api/health", tags=["health"])


def _context(request: Request) -> RuntimeContext:
    return request.app.state.runtime  # type: ignore[no-any-return]


@router.get("", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return _context(request).capabilities()


@router.post("/probe")
async def probe(request: Request) -> dict[str, Any]:
    """实测外部能力：真实发起一次文本补全与一次编码。

    返回结构中的 `ok` 只表示本次实测结果，不代表验收通过。
    """

    context = _context(request)
    model_provider: ModelProvider = context.model_provider
    embedding_provider: EmbeddingProvider = context.embedding_provider
    report: dict[str, Any] = {"runMode": context.settings.run_mode}

    text_started = time.perf_counter()
    try:
        result = model_provider.complete(
            [ChatMessage(role="user", content="只回复两个字：可用")], max_tokens=16
        )
        report["llm"] = {
            "ok": True,
            "modelId": result.model,
            "isMock": result.is_mock,
            "latencySeconds": round(time.perf_counter() - text_started, 3),
            "replyPreview": result.text[:40],
        }
    except Exception as exc:
        report["llm"] = {
            "ok": False,
            "errorCode": getattr(exc, "code", type(exc).__name__),
            "message": str(exc)[:200],
            "latencySeconds": round(time.perf_counter() - text_started, 3),
        }

    encode_started = time.perf_counter()
    try:
        batch = embedding_provider.encode(["T区容易出油", "两颊干燥且底妆容易卡粉"])
        report["embedding"] = {
            "ok": True,
            "modelId": batch.model_id,
            "dimension": batch.dimension,
            "sparseChannels": [len(item.indices) for item in batch.sparse],
            "isMock": batch.is_mock,
            "latencySeconds": round(time.perf_counter() - encode_started, 3),
            "revision": batch.model_revision,
        }
    except Exception as exc:
        report["embedding"] = {
            "ok": False,
            "errorCode": getattr(exc, "code", type(exc).__name__),
            "message": str(exc)[:200],
            "latencySeconds": round(time.perf_counter() - encode_started, 3),
        }

    report["vision"] = {
        "configured": model_provider.supports_vision,
        "note": (
            "已配置多模态模型，可用图片用例实测"
            if model_provider.supports_vision
            else "未配置多模态模型：图片线索提取无法真实执行，AC-01「看图」live 链路保留未通过"
        ),
    }
    return report
