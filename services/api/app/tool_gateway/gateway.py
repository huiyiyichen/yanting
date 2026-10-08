"""ToolGateway：所有工具调用的统一入口。

调用链（工程规范第 5.1 节）：
    Agent → ToolRequest → 工具白名单 → 参数 Schema 校验 → 权限/风险校验
          → 幂等校验 → 具体工具适配器 → ToolResult → 业务状态机

不变量：
- 未注册工具、非法参数、越权调用一律抛错，不返回「近似成功」；
- 高风险动作不会被自动执行；
- 相同幂等键的重复请求返回**首次结果**，不重复产生副作用
  （LangGraph 中断恢复可能重跑节点，仅靠前端禁用按钮无法防重复）。
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from sqlalchemy.orm import Session

from app.domain.enums import RiskLevel, ToolName
from app.errors import ToolAccessDenied
from app.logging_setup import get_logger, log_event
from app.tool_gateway.contracts import ToolContext, ToolRequest, ToolResult
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)


class ToolGateway:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        session: Session | None = None,
        settings: Any | None = None,
        embedding_provider: Any | None = None,
        rerank_provider: Any | None = None,
    ) -> None:
        self._registry = registry
        self._session = session
        self._idempotency: dict[str, ToolResult] = {}
        self._call_log: list[dict[str, Any]] = []
        # 运行时依赖表：只在工具确实声明了该参数时才注入。
        # 这样工具可以按需声明 session / settings / embedding_provider，
        # 而不必让每个工具都接受全部依赖。
        self._runtime_deps: dict[str, Any] = {
            "session": session,
            "settings": settings,
            "embedding_provider": embedding_provider,
            "rerank_provider": rerank_provider,
        }

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def call_log(self) -> list[dict[str, Any]]:
        """本次运行的工具调用轨迹，用于客服面板与审计（不含模型隐藏思考）。"""

        return list(self._call_log)

    def invoke(
        self,
        tool: ToolName | str,
        arguments: dict[str, Any],
        *,
        context: ToolContext | None = None,
        idempotency_key: str | None = None,
        as_agent: bool = True,
    ) -> ToolResult:
        ctx = context or ToolContext()

        # 1) 白名单
        spec = self._registry.get(tool)

        # 2) 风险与权限校验（在参数校验之前，越权请求不进入业务逻辑）
        if as_agent:
            spec = self._registry.assert_agent_may_call(spec.name)
        elif spec.risk_level is RiskLevel.HIGH_RISK:
            raise ToolAccessDenied(
                f"高风险工具 {spec.name.value} 需要人工确认流程，不在本接口开放",
                detail="本期不执行真实退款、换货、维修或派单",
            )

        # 3) 幂等：同一键返回首次结果，不重复执行
        cache_key = self._cache_key(spec.name, arguments, idempotency_key)
        if cache_key is not None and cache_key in self._idempotency:
            cached = self._idempotency[cache_key]
            log_event(
                logger,
                "tool_idempotent_replay",
                tool=spec.name.value,
                idempotency_key=idempotency_key,
            )
            return cached

        # 4) 参数 Schema 校验
        validated = self._registry.validate_arguments(spec.name, arguments)

        # 5) 执行
        request = ToolRequest(
            tool=spec.name,
            arguments=validated.model_dump(by_alias=True),
            idempotency_key=idempotency_key,
            context=ctx,
        )
        try:
            call_kwargs: dict[str, Any] = {
                **validated.model_dump(),
                "tool_request_id": request.tool_request_id,
                "idempotency_key": idempotency_key,
                "context": ctx,
            }
            # 持久化与检索类工具需要数据库会话、配置与编码器。
            # 只在工具确实声明了对应参数时注入，避免给只读工具塞入
            # 未声明的关键字参数（那会被当成签名错误）。
            for dep_name, dep_value in self._runtime_deps.items():
                if dep_value is not None and _accepts_parameter(spec.handler, dep_name):
                    call_kwargs[dep_name] = dep_value
            result = spec.handler(**call_kwargs)
            if not isinstance(result, ToolResult):
                raise ToolAccessDenied(
                    f"{spec.name.value} 返回了非 ToolResult 的对象",
                    detail="工具实现必须返回 ToolResult，不允许伪造返回结构",
                )
        except TypeError as exc:
            # 工具签名与 Schema 不匹配属于实现错误，必须暴露而不是吞掉
            raise ToolAccessDenied(
                f"{spec.name.value} 调用签名不匹配",
                detail=str(exc)[:400],
            ) from exc

        # 工具实现返回的 tool_request_id 统一为网关生成的 id
        result = ToolResult(
            tool=result.tool,
            status=result.status,
            data=result.data,
            message=result.message,
            tool_request_id=request.tool_request_id,
        )

        if cache_key is not None:
            self._idempotency[cache_key] = result

        self._call_log.append(
            {
                "tool": spec.name.value,
                "status": result.status,
                "riskLevel": spec.risk_level.value,
                "toolRequestId": request.tool_request_id,
                "arguments": _redact(validated.model_dump(by_alias=True)),
                "message": result.message[:200],
            }
        )
        log_event(
            logger,
            "tool_invoked",
            tool=spec.name.value,
            status=result.status,
            risk_level=spec.risk_level.value,
            tool_request_id=request.tool_request_id,
        )
        return result

    @staticmethod
    def _cache_key(
        tool: ToolName, arguments: dict[str, Any], idempotency_key: str | None
    ) -> str | None:
        if not idempotency_key:
            return None
        payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
        return f"{tool.value}|{idempotency_key}|{hash(payload)}"


def _accepts_parameter(handler: Any, name: str) -> bool:
    """工具是否声明了某个关键字参数。

    用于判断是否需要注入 `session` 等运行时依赖。
    带 `**kwargs` 的处理器一律视为接受（显式声明了可变关键字）。
    """

    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        return False
    if name in signature.parameters:
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _redact(payload: dict[str, Any]) -> dict[str, Any]:
    """工具参数入库前的脱敏：不保存手机号、完整订单号等。

    这里只做最小化：工具参数本身已被 PRD 限制为不含敏感字段，
    仍对明显的敏感键名做掩码，避免将来新增字段时误留。
    """

    sensitive_markers = ("phone", "mobile", "address", "id_card", "token", "secret", "key")
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if any(marker in key.lower() for marker in sensitive_markers):
            redacted[key] = "***"
        elif isinstance(value, dict):
            redacted[key] = _redact(value)
        else:
            redacted[key] = value
    return redacted
