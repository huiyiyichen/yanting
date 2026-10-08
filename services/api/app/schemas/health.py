"""健康检查与运行状态契约。

`/api/health` 必须如实反映外部能力是否接通：未配置的模型服务报告为
`unavailable`，不允许静默回退成 mock 后仍报告 live 可用。
"""

from __future__ import annotations

from typing import Literal

from app.schemas.base import ApiModel

CapabilityState = Literal["ready", "unavailable", "unknown"]


class CapabilityStatus(ApiModel):
    """单项外部能力的真实状态。"""

    name: str
    state: CapabilityState
    detail: str
    model_id: str | None = None
    revision: str | None = None


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    run_mode: Literal["live", "mock"]
    contract_version: str
    app_version: str
    database: CapabilityStatus
    llm: CapabilityStatus
    vision: CapabilityStatus
    embedding: CapabilityStatus
    knowledge_index: CapabilityStatus
    #: 可选精排：未配置时如实报 unavailable（不写"已启用"）
    rerank: CapabilityStatus
