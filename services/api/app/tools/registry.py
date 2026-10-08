"""工具注册表：白名单与参数 Schema 的唯一来源。

安全要求（工程规范第 5 章）：
- 每个工具有独立输入/输出 Schema；
- 模型不得伪造工具返回结果；
- 未注册的工具名一律拒绝，不做兜底放行。

参数名使用 `camelCase` 别名，与 API 契约一致；模型输出经 Pydantic 校验后才允许执行。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.domain.enums import RiskLevel, ToolName
from app.errors import ToolAccessDenied
from app.tool_gateway.contracts import ToolContext, ToolResult

__all__ = [
    "CaseFactInput",
    "CreateRequestInput",
    "DealerLookupInput",
    "KnowledgeSearchInput",
    "OrderLookupInput",
    "ProductLookupInput",
    "RatingInput",
    "ToolRegistry",
    "ToolSpec",
    "WarrantyEvaluateInput",
    "build_default_registry",
]


class _Args(BaseModel):
    """工具入参基类：camelCase 别名 + 禁止未声明字段。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class KnowledgeSearchInput(_Args):
    query: str = Field(min_length=1, max_length=2000)
    product_model: str | None = None
    country_code: str | None = Field(default=None, max_length=8)
    purchase_channel: str | None = None
    # 客户会话不能读到内部资料：该字段由服务端按会话角色决定，模型不能自行提升
    audience: str | None = None


class OrderLookupInput(_Args):
    customer_id: str | None = None
    order_id: str | None = None
    order_no_masked: str | None = None
    product_id: str | None = None


class ProductLookupInput(_Args):
    query: str | None = None
    product_model: str | None = None


class DealerLookupInput(_Args):
    seller_name_raw: str = Field(min_length=1, max_length=200)
    country_code: str | None = Field(default=None, max_length=8)
    purchase_channel: str | None = None


class WarrantyEvaluateInput(_Args):
    order_id: str = Field(min_length=1)
    on_date: str | None = None


class CaseFactInput(_Args):
    case_id: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    value: Any = None


class CreateRequestInput(_Args):
    """生成售后申请草稿。

    只生成草稿，不执行退款/换货/维修等真实动作（PRD 第 1.4 节）。
    """

    case_id: str = Field(min_length=1)
    request_type: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class RatingInput(_Args):
    case_id: str = Field(min_length=1)
    action: str = Field(pattern="^(request|submit|skip)$")
    rating: int | None = Field(default=None, ge=1, le=5)


class TroubleshootingPlanInput(_Args):
    case_id: str = Field(min_length=1)
    fault_type: str | None = None
    product_model: str | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """工具规格。`risk_level` 决定是否允许自动执行。"""

    name: ToolName
    risk_level: RiskLevel
    input_model: type[BaseModel]
    handler: Callable[..., ToolResult]
    description: str
    # 是否允许在无人确认的情况下由 Agent 调用
    agent_callable: bool = True
    read_only: bool = True
    tags: tuple[str, ...] = field(default_factory=tuple)


class ToolRegistry:
    """工具白名单。未注册名称一律拒绝。"""

    def __init__(self, specs: list[ToolSpec] | None = None) -> None:
        self._specs: dict[ToolName, ToolSpec] = {}
        for spec in specs or []:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"工具重复注册：{spec.name.value}")
        self._specs[spec.name] = spec

    def get(self, name: ToolName | str) -> ToolSpec:
        try:
            resolved = ToolName(name) if not isinstance(name, ToolName) else name
        except ValueError as exc:
            raise ToolAccessDenied(
                f"未知工具：{name}",
                detail=f"允许的工具：{sorted(item.value for item in self._specs)}",
            ) from exc
        spec = self._specs.get(resolved)
        if spec is None:
            raise ToolAccessDenied(
                f"工具未在本次运行中注册：{resolved.value}",
                detail="未注册工具不会被兜底执行",
            )
        return spec

    def names(self) -> list[str]:
        return sorted(item.value for item in self._specs)

    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def validate_arguments(self, name: ToolName | str, arguments: dict[str, Any]) -> BaseModel:
        """按工具的独立 Schema 校验参数。非法参数直接拒绝，不做静默裁剪。"""

        spec = self.get(name)
        try:
            return spec.input_model.model_validate(arguments)
        except Exception as exc:
            raise ToolAccessDenied(
                f"{spec.name.value} 参数校验失败",
                detail=str(exc)[:600],
            ) from exc

    def assert_agent_may_call(self, name: ToolName | str) -> ToolSpec:
        spec = self.get(name)
        if not spec.agent_callable:
            raise ToolAccessDenied(
                f"工具 {spec.name.value} 不允许由 Agent 自动调用",
                detail=f"风险等级={spec.risk_level.value}",
            )
        if spec.risk_level is RiskLevel.HIGH_RISK:
            raise ToolAccessDenied(
                f"高风险工具 {spec.name.value} 禁止自动执行",
                detail="本期不开放真实退款、换货、维修或派单",
            )
        return spec


def build_default_registry() -> ToolRegistry:
    """注册本期的全部工具。

    `create_after_sales_request` 只能生成草稿，因此风险等级为 `request_creation`
    且允许 Agent 调用；真正的执行类工具（`high_risk`）本期不注册。
    """

    from app.tools import query_tools

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name=ToolName.KNOWLEDGE_SEARCH,
            risk_level=RiskLevel.READ_ONLY,
            input_model=KnowledgeSearchInput,
            handler=query_tools.knowledge_search_tool,
            description="按适用条件与权限检索知识片段，返回带来源定位的证据",
            tags=("knowledge", "evidence"),
        )
    )
    registry.register(
        ToolSpec(
            name=ToolName.ORDER_LOOKUP,
            risk_level=RiskLevel.READ_ONLY,
            input_model=OrderLookupInput,
            handler=query_tools.order_lookup,
            description="按客户/订单号查询脱敏订单",
            tags=("order",),
        )
    )
    registry.register(
        ToolSpec(
            name=ToolName.PRODUCT_LOOKUP,
            risk_level=RiskLevel.READ_ONLY,
            input_model=ProductLookupInput,
            handler=query_tools.product_lookup,
            description="产品候选召回或同名型号全部候选",
            tags=("product", "disambiguation"),
        )
    )
    registry.register(
        ToolSpec(
            name=ToolName.DEALER_LOOKUP,
            risk_level=RiskLevel.READ_ONLY,
            input_model=DealerLookupInput,
            handler=query_tools.dealer_lookup,
            description="按国家精确匹配 + 卖家模糊匹配核验授权",
            tags=("dealer", "authorization"),
        )
    )
    registry.register(
        ToolSpec(
            name=ToolName.WARRANTY_EVALUATE,
            risk_level=RiskLevel.READ_ONLY,
            input_model=WarrantyEvaluateInput,
            handler=query_tools.warranty_evaluate,
            description="按订单事实计算质保状态（只做日期算术）",
            tags=("warranty",),
        )
    )
    registry.register(
        ToolSpec(
            name=ToolName.CREATE_AFTER_SALES_REQUEST,
            risk_level=RiskLevel.REQUEST_CREATION,
            input_model=CreateRequestInput,
            handler=query_tools.create_request_draft,
            description="生成售后申请草稿并进入待人工确认；不执行真实业务动作",
            read_only=False,
            tags=("request", "human_confirmation"),
        )
    )
    registry.register(
        ToolSpec(
            name=ToolName.RECORD_CASE_FACT,
            risk_level=RiskLevel.RECORDING,
            input_model=CaseFactInput,
            handler=query_tools.record_case_fact,
            description="写入经过程序校验的最小案件事实",
            read_only=False,
            tags=("case",),
        )
    )
    registry.register(
        ToolSpec(
            name=ToolName.RECORD_RATING,
            risk_level=RiskLevel.RECORDING,
            input_model=RatingInput,
            handler=query_tools.record_rating,
            description="发起、提交或跳过满意度评价",
            read_only=False,
            tags=("rating",),
        )
    )
    registry.register(
        ToolSpec(
            name=ToolName.TROUBLESHOOTING_PLAN,
            risk_level=RiskLevel.READ_ONLY,
            input_model=TroubleshootingPlanInput,
            handler=query_tools.troubleshooting_plan,
            description="依据 SOP 证据生成分步排障引导",
            tags=("troubleshooting",),
        )
    )
    return registry


def tool_context_for(
    *, case_id: str | None = None, conversation_id: str | None = None, actor: str = "agent"
) -> ToolContext:
    return ToolContext(
        read_only=True, case_id=case_id, conversation_id=conversation_id, requested_by=actor
    )
