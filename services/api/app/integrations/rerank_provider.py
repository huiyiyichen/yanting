"""重排序适配器：把「召回候选」按与查询的相关性重新排序。

为什么要单独一个模块：检索的第二段（精排）与第一段（召回）是两种能力，
供应商、模型、可用性都不同。工程规范第 12 节把它列为**可选增强**，
只有在校准集上证明排序不足时才接入（本项目 CAL-03 就是这种情况）。

诚实边界：
- 远端 `/rerank` 只给出"查询—文档"相关性分数，**不产生向量**，因此它不能
  替代编码模型，也不会改变索引；
- 未配置时调用方必须按"没有重排序"处理，报告里不得写成已启用。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from app.errors import ProviderNotConfigured, ProviderRequestFailed, ProviderTimeout
from app.logging_setup import get_logger, log_event

logger = get_logger(__name__)

#: 硅基流动等 OpenAI 兼容网关上的常见可选模型（页面下拉用，不写死唯一解）
RERANK_MODEL_OPTIONS: tuple[str, ...] = (
    "BAAI/bge-reranker-v2-m3",
    "Qwen/Qwen3-Reranker-8B",
    "Qwen/Qwen3-Reranker-4B",
    "Qwen/Qwen3-Reranker-0.6B",
    "Qwen/Qwen3-VL-Reranker-8B",
)


@dataclass(frozen=True, slots=True)
class RerankHit:
    index: int
    score: float


class RerankProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    def available(self) -> bool: ...

    def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[RerankHit]: ...

    def describe(self) -> dict[str, str]: ...


class HttpRerankProvider:
    """OpenAI 兼容 `/rerank` 服务（硅基流动、Jina、Cohere 风格一致）。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id
        self._timeout = timeout_seconds

    @property
    def model_id(self) -> str:
        return self._model_id

    def available(self) -> bool:
        return bool(self._base_url and self._model_id)

    def _endpoint(self, path: str) -> str:
        """拼出 `/v1/...` 端点。

        用户填的地址两种写法都常见：`https://host` 与 `https://host/v1`。
        统一归一化，避免出现 `/v1/v1/rerank` 这种 404。
        """

        base = self._base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        return f"{base}/v1/{path}"

    def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[RerankHit]:
        if not self.available():
            raise ProviderNotConfigured(
                "重排序服务未配置",
                detail="需要 ANKER_AGENT_RERANK_BASE_URL 与 ANKER_AGENT_RERANK_MODEL",
            )
        if not documents:
            return []

        payload: dict[str, Any] = {
            "model": self._model_id,
            "query": query,
            "documents": documents,
        }
        if top_n is not None:
            payload["top_n"] = top_n
        request = urllib.request.Request(
            self._endpoint("rerank"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}),
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderRequestFailed(
                f"重排序服务返回 HTTP {exc.code}",
                detail=exc.read().decode("utf-8", "replace")[:300],
            ) from exc
        except TimeoutError as exc:
            raise ProviderTimeout("重排序服务超时") from exc
        except Exception as exc:
            raise ProviderRequestFailed(
                f"重排序请求失败：{type(exc).__name__}", detail=str(exc)[:300]
            ) from exc

        raw_results = body.get("results") or body.get("data") or []
        hits: list[RerankHit] = []
        for item in raw_results:
            index = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if index is None or score is None:
                continue
            hits.append(RerankHit(index=int(index), score=float(score)))
        if not hits:
            raise ProviderRequestFailed(
                "重排序服务返回空结果", detail=json.dumps(body, ensure_ascii=False)[:200]
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        log_event(
            logger,
            "rerank_completed",
            model=self._model_id,
            documents=len(documents),
            latency_seconds=round(time.perf_counter() - started, 3),
        )
        return hits

    def describe(self) -> dict[str, str]:
        return {
            "backend": "http",
            "model_id": self._model_id,
            "base_url_set": str(bool(self._base_url)),
        }


def build_rerank_provider(settings: Any) -> RerankProvider | None:
    """按配置构建重排序适配器；未配置时返回 `None`（= 不做重排序）。"""

    backend = getattr(settings, "rerank_backend", "none")
    if backend == "mock":
        if getattr(settings, "run_mode", "live") != "mock":
            raise ProviderNotConfigured(
                "live 模式不允许 mock 重排序后端",
                detail="如需联调请显式设置 ANKER_AGENT_RUN_MODE=mock，并在报告中标注",
            )
        return None
    if backend != "http":
        return None
    provider = HttpRerankProvider(
        base_url=getattr(settings, "rerank_base_url", ""),
        api_key=getattr(settings, "rerank_api_key", ""),
        model_id=getattr(settings, "rerank_model", ""),
        timeout_seconds=float(getattr(settings, "rerank_timeout_seconds", 30.0)),
    )
    return provider if provider.available() else None
