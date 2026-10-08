"""Agent 编排的共享状态与契约。

三个核心功能的字段对应关系（PRD 第 3 章）：
- F1 多模态故障理解 → `CaseFacts`、`product_candidates`、`missing_facts`、`uncertainty_flags`
- F2 复杂诉求识别与服务分流 → `customer_intents`、`service_route`、`emotion_level`、
  `complaint_risk`、`allowed_actions`、`human_intervention_required`
- F3 证据驱动的自主售后办理 → `evidence`、`troubleshooting_steps`、`request_draft`

边界（PRD 第 4 节）：
- Agent 可自主完成理解、追问、检索、事实归一化、低风险排障、状态解释和申请草稿；
- Agent **不得**自主执行退款、换货、维修、补件，也不得在无证据时输出确定承诺。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import (
    CaseStatus,
    ComplaintRisk,
    ConversationStage,
    CustomerIntent,
    DealerAuthorizationStatus,
    EmotionLevel,
    FaultPart,
    FaultType,
    KnowledgeHitStatus,
    RequestType,
    WarrantyStatus,
)

# 需要人工确认的申请类型（会产生业务承诺）
HIGH_RISK_REQUEST_TYPES = frozenset(
    {
        RequestType.REFUND,
        RequestType.REPLACEMENT,
        RequestType.REPAIR,
        RequestType.PARTS_RESHIPMENT,
    }
)

# 意图 -> 申请类型的固定映射
INTENT_TO_REQUEST_TYPE: dict[CustomerIntent, RequestType] = {
    CustomerIntent.REFUND: RequestType.REFUND,
    CustomerIntent.REPLACEMENT: RequestType.REPLACEMENT,
    CustomerIntent.REPAIR: RequestType.REPAIR,
    CustomerIntent.PARTS: RequestType.PARTS_RESHIPMENT,
}


@dataclass
class CaseFacts:
    """结构化案件事实（F1 输出）。字段缺失表示「尚未确认」，不用自由文本代替。"""

    product_model: str | None = None
    product_id: str | None = None
    product_category: str | None = None
    fault_type: FaultType = FaultType.UNKNOWN
    fault_part: FaultPart = FaultPart.UNKNOWN
    phenomenon: str = ""
    country_code: str | None = None
    purchase_channel: str | None = None
    seller_name_raw: str | None = None
    order_id: str | None = None

    # 图片只能证明可见现象，不能证明内部根因
    observed_from_image: list[str] = field(default_factory=list)

    def missing_required(self) -> list[str]:
        """当前办理路径所需的最小事实。"""

        missing: list[str] = []
        if not self.product_model:
            missing.append("product_model")
        if not self.country_code:
            missing.append("country_code")
        return missing

    def to_dict(self) -> dict[str, Any]:
        return {
            "productModel": self.product_model,
            "productId": self.product_id,
            "productCategory": self.product_category,
            "faultType": self.fault_type.value,
            "faultPart": self.fault_part.value,
            "phenomenon": self.phenomenon,
            "countryCode": self.country_code,
            "purchaseChannel": self.purchase_channel,
            "sellerNameRaw": self.seller_name_raw,
            "orderId": self.order_id,
            "observedFromImage": list(self.observed_from_image),
        }


@dataclass
class AgentDecision:
    """一次 Agent 决策的完整结果，供路由返回与审计记录。"""

    stage: ConversationStage
    reply: str
    facts: CaseFacts
    customer_intents: list[CustomerIntent]
    emotion_level: EmotionLevel
    complaint_risk: ComplaintRisk
    service_route: str
    allowed_actions: list[str]
    missing_facts: list[str]
    product_candidates: list[dict[str, Any]] = field(default_factory=list)
    uncertainty_flags: list[str] = field(default_factory=list)
    # 证据保持 knowledge_search 工具返回的原始结构（snake_case），
    # 由 API 层统一序列化为 camelCase。中间层改名会导致静默取到空值（已踩过）。
    evidence: list[dict[str, Any]] = field(default_factory=list)
    retrieval_id: str | None = None
    knowledge_hit_status: KnowledgeHitStatus | None = None
    warranty_status: WarrantyStatus | None = None
    dealer_authorization_status: DealerAuthorizationStatus | None = None
    troubleshooting_steps: list[str] = field(default_factory=list)
    request_draft: dict[str, Any] | None = None
    human_intervention_required: bool = False
    human_intervention_reason: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model_id: str | None = None
    prompt_version: str | None = None
    trace_id: str | None = None
    case_status: CaseStatus = CaseStatus.OPEN
    rating_requested: bool = False
    # 幂等重放时回填：本条客户消息与当时自动回复的消息 ID，
    # 让路由能返回**原始**消息而不是重新猜测（否则重复提交会取错消息或报 500）
    customer_message_id: str | None = None
    reply_message_id: str | None = None
    is_idempotent_replay: bool = False
    notes: list[str] = field(default_factory=list)
