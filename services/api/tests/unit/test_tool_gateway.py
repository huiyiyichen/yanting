"""ToolGateway 测试。

覆盖 PRD AC-08（高风险动作自动执行次数 0）、AC-30（接口权限边界）与
工程规范第 5 章的调用链要求。
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from app.domain.enums import RiskLevel, ToolName
from app.errors import ToolAccessDenied
from app.tool_gateway.contracts import ToolContext, ToolResult
from app.tool_gateway.gateway import ToolGateway
from app.tools.registry import (
    ToolRegistry,
    ToolSpec,
    build_default_registry,
)


class _EchoInput(BaseModel):
    model_config = {"extra": "forbid"}
    value: str


def _echo(*, value: str, tool_request_id: str | None = None, **_: Any) -> ToolResult:
    return ToolResult(
        tool=ToolName.ORDER_LOOKUP,
        status="ok",
        data={"echo": value},
        message="echo",
        tool_request_id=tool_request_id,
    )


class _Counter:
    """记录实际执行次数的处理器，用于验证幂等不重复执行。"""

    def __init__(self) -> None:
        self.calls = 0

    def handler(self, *, value: str, tool_request_id: str | None = None, **_: Any) -> ToolResult:
        self.calls += 1
        return ToolResult(
            tool=ToolName.ORDER_LOOKUP,
            status="ok",
            data={"count": self.calls, "value": value},
            message="counted",
            tool_request_id=tool_request_id,
        )


def _registry_with_counter(counter: _Counter) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name=ToolName.ORDER_LOOKUP,
            risk_level=RiskLevel.READ_ONLY,
            input_model=_EchoInput,
            handler=counter.handler,
            description="计数用工具",
        )
    )
    return registry


class TestWhitelist:
    def test_unknown_tool_name_is_rejected(self) -> None:
        gateway = ToolGateway(build_default_registry())
        with pytest.raises(ToolAccessDenied, match="未知工具"):
            gateway.invoke("delete_order", {})

    def test_unregistered_known_tool_is_rejected(self) -> None:
        """枚举里存在但本次未注册的工具也不得执行。"""

        registry = ToolRegistry()
        gateway = ToolGateway(registry)
        with pytest.raises(ToolAccessDenied, match="未在本次运行中注册"):
            gateway.invoke(ToolName.KNOWLEDGE_SEARCH, {"query": "x"})

    def test_registered_tools_match_expected_set(self) -> None:
        registry = build_default_registry()
        assert registry.names() == [
            "create_after_sales_request",
            "dealer_lookup",
            "knowledge_search",
            "order_lookup",
            "product_lookup",
            "record_case_fact",
            "record_rating",
            "troubleshooting_plan",
            "warranty_evaluate",
        ]


class TestArgumentValidation:
    def test_missing_required_argument_is_rejected(self) -> None:
        gateway = ToolGateway(build_default_registry())
        with pytest.raises(ToolAccessDenied, match="参数校验失败"):
            gateway.invoke(ToolName.PRODUCT_LOOKUP, {"unexpected": 1})

    def test_extra_argument_is_rejected(self) -> None:
        gateway = ToolGateway(build_default_registry())
        with pytest.raises(ToolAccessDenied, match="参数校验失败"):
            gateway.invoke(ToolName.PRODUCT_LOOKUP, {"productModel": "A1 Pro", "evil": True})

    def test_camel_case_arguments_are_accepted(self) -> None:
        gateway = ToolGateway(build_default_registry())
        result = gateway.invoke(ToolName.PRODUCT_LOOKUP, {"productModel": "A1 Pro"})
        assert result.ok
        assert result.data["requiresDisambiguation"] is True

    def test_snake_case_arguments_also_accepted(self) -> None:
        gateway = ToolGateway(build_default_registry())
        result = gateway.invoke(ToolName.PRODUCT_LOOKUP, {"product_model": "A1 Pro"})
        assert result.ok


class TestRiskBoundary:
    def test_high_risk_tool_cannot_be_called_by_agent(self) -> None:
        """AC-08：高风险工具禁止自动执行。"""

        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name=ToolName.CREATE_AFTER_SALES_REQUEST,
                risk_level=RiskLevel.HIGH_RISK,
                input_model=_EchoInput,
                handler=_echo,
                description="假装的高风险执行工具",
            )
        )
        gateway = ToolGateway(registry)
        with pytest.raises(ToolAccessDenied, match="高风险工具"):
            gateway.invoke(ToolName.CREATE_AFTER_SALES_REQUEST, {"value": "refund"})

    def test_high_risk_tool_also_blocked_for_operator_path(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name=ToolName.CREATE_AFTER_SALES_REQUEST,
                risk_level=RiskLevel.HIGH_RISK,
                input_model=_EchoInput,
                handler=_echo,
                description="假装的高风险执行工具",
            )
        )
        gateway = ToolGateway(registry)
        with pytest.raises(ToolAccessDenied, match="需要人工确认流程"):
            gateway.invoke(ToolName.CREATE_AFTER_SALES_REQUEST, {"value": "x"}, as_agent=False)

    def test_request_creation_is_allowed_for_agent(self) -> None:
        """生成草稿属于允许的自主行为，风险等级不是 high_risk。"""

        registry = build_default_registry()
        spec = registry.get(ToolName.CREATE_AFTER_SALES_REQUEST)
        assert spec.risk_level is RiskLevel.REQUEST_CREATION
        assert spec.agent_callable is True

    def test_agent_callable_flag_is_enforced(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name=ToolName.ORDER_LOOKUP,
                risk_level=RiskLevel.READ_ONLY,
                input_model=_EchoInput,
                handler=_echo,
                description="仅人工可调用",
                agent_callable=False,
            )
        )
        gateway = ToolGateway(registry)
        with pytest.raises(ToolAccessDenied, match="不允许由 Agent 自动调用"):
            gateway.invoke(ToolName.ORDER_LOOKUP, {"value": "x"})
        # 非 Agent 路径仍可调用
        assert gateway.invoke(ToolName.ORDER_LOOKUP, {"value": "x"}, as_agent=False).ok


class TestIdempotency:
    def test_same_key_does_not_execute_twice(self) -> None:
        """LangGraph 恢复可能重跑节点：同一幂等键必须复用首次结果。"""

        counter = _Counter()
        gateway = ToolGateway(_registry_with_counter(counter))
        first = gateway.invoke(ToolName.ORDER_LOOKUP, {"value": "a"}, idempotency_key="k-1")
        second = gateway.invoke(ToolName.ORDER_LOOKUP, {"value": "a"}, idempotency_key="k-1")
        assert counter.calls == 1
        assert first.data == second.data
        assert first.tool_request_id == second.tool_request_id

    def test_different_keys_execute_twice(self) -> None:
        counter = _Counter()
        gateway = ToolGateway(_registry_with_counter(counter))
        gateway.invoke(ToolName.ORDER_LOOKUP, {"value": "a"}, idempotency_key="k-1")
        gateway.invoke(ToolName.ORDER_LOOKUP, {"value": "a"}, idempotency_key="k-2")
        assert counter.calls == 2

    def test_without_key_always_executes(self) -> None:
        counter = _Counter()
        gateway = ToolGateway(_registry_with_counter(counter))
        gateway.invoke(ToolName.ORDER_LOOKUP, {"value": "a"})
        gateway.invoke(ToolName.ORDER_LOOKUP, {"value": "a"})
        assert counter.calls == 2


class TestCallLog:
    def test_call_log_records_tool_and_status(self) -> None:
        gateway = ToolGateway(build_default_registry())
        gateway.invoke(ToolName.PRODUCT_LOOKUP, {"productModel": "A1 Pro"})
        log = gateway.call_log()
        assert len(log) == 1
        assert log[0]["tool"] == "product_lookup"
        assert log[0]["status"] == "ok"
        assert log[0]["riskLevel"] == "read_only"

    def test_call_log_redacts_sensitive_keys(self) -> None:
        counter = _Counter()
        registry = ToolRegistry()

        class _SensitiveInput(BaseModel):
            model_config = {"extra": "forbid"}
            phone: str

        registry.register(
            ToolSpec(
                name=ToolName.ORDER_LOOKUP,
                risk_level=RiskLevel.READ_ONLY,
                input_model=_SensitiveInput,
                handler=lambda **kw: ToolResult(
                    tool=ToolName.ORDER_LOOKUP, status="ok", data={}, message="ok"
                ),
                description="敏感参数",
            )
        )
        gateway = ToolGateway(registry)
        gateway.invoke(ToolName.ORDER_LOOKUP, {"phone": "13800138000"})
        assert gateway.call_log()[0]["arguments"]["phone"] == "***"
        del counter


class TestHandlerContract:
    def test_non_toolresult_return_is_rejected(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name=ToolName.ORDER_LOOKUP,
                risk_level=RiskLevel.READ_ONLY,
                input_model=_EchoInput,
                handler=lambda **_: {"fake": "dict"},  # type: ignore[arg-type,return-value]
                description="返回错误类型",
            )
        )
        gateway = ToolGateway(registry)
        with pytest.raises(ToolAccessDenied, match="非 ToolResult"):
            gateway.invoke(ToolName.ORDER_LOOKUP, {"value": "x"})

    def test_signature_mismatch_is_reported(self) -> None:
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                name=ToolName.ORDER_LOOKUP,
                risk_level=RiskLevel.READ_ONLY,
                input_model=_EchoInput,
                handler=lambda wrong_name: ToolResult(  # type: ignore[arg-type,return-value]
                    tool=ToolName.ORDER_LOOKUP, status="ok"
                ),
                description="签名不匹配",
            )
        )
        gateway = ToolGateway(registry)
        with pytest.raises(ToolAccessDenied, match="调用签名不匹配"):
            gateway.invoke(ToolName.ORDER_LOOKUP, {"value": "x"})


class TestKnowledgeAudienceBoundary:
    def test_customer_context_cannot_read_internal(self) -> None:
        """AC-30：客户上下文越权读取内部知识必须被服务端拒绝。"""

        gateway = ToolGateway(build_default_registry())
        result = gateway.invoke(
            ToolName.KNOWLEDGE_SEARCH,
            {"query": "退款条件", "audience": "internal"},
            context=ToolContext(read_only=True, requested_by="agent"),
        )
        assert result.status == "denied"
        assert "无权" in result.message

    def test_support_context_may_request_internal(self) -> None:
        """客服上下文请求 internal 时不被权限拦截（此处因缺依赖返回 failed，非 denied）。"""

        gateway = ToolGateway(build_default_registry())
        result = gateway.invoke(
            ToolName.KNOWLEDGE_SEARCH,
            {"query": "退款条件", "audience": "internal"},
            context=ToolContext(read_only=True, requested_by="support"),
        )
        assert result.status != "denied"
