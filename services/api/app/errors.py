"""领域级异常：区分"外部能力不可用"和"业务规则拒绝"。

原则：模型服务缺失时给出真实错误，不静默改成固定回复并报告 live 通过。
"""

from __future__ import annotations


class AnkerAgentError(Exception):
    """本项目所有可预期错误的基类。"""

    code = "agent_error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ProviderNotConfigured(AnkerAgentError):
    """外部能力未配置（缺 base_url / key / model）。"""

    code = "provider_not_configured"


class ProviderRequestFailed(AnkerAgentError):
    """外部能力请求失败（网络、HTTP 错误、返回体非法）。"""

    code = "provider_request_failed"


class ProviderTimeout(AnkerAgentError):
    """外部能力超时。与"人工等待"完全分开。"""

    code = "provider_timeout"


class ModelOutputInvalid(AnkerAgentError):
    """模型输出不符合结构/业务约束，必须拒绝而不是猜测修复。"""

    code = "model_output_invalid"


class ToolAccessDenied(AnkerAgentError):
    """工具不在白名单、权限不足或参数校验失败。"""

    code = "tool_access_denied"


class RiskBoundaryViolation(AnkerAgentError):
    """试图自动执行高风险动作。属于红线错误。"""

    code = "risk_boundary_violation"


class ConflictError(AnkerAgentError):
    """并发或状态冲突：旧版本确认、重复提交、过期候选等。"""

    code = "conflict"


class NotFoundError(AnkerAgentError):
    code = "not_found"


class ValidationRejected(AnkerAgentError):
    """业务规则校验拒绝（区别于 Pydantic 结构校验）。"""

    code = "validation_rejected"
