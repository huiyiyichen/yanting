"""服务分流与沟通策略（F2）。

规则来源：PRD 第 3.3 节与第 4.3 节。

硬性边界：
- 单纯愤怒**不**触发人工转接；Agent 先安抚并继续处理允许的事项；
- 情绪只影响沟通策略，不改变质保规则或赔付条件；
- 投诉风险单独记录，不作为自动转接开关；
- 「补问两轮仍无新增信息」是**单个必要事实**的计数，不是全会话「两轮就转人工」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.agent.contracts import (
    HIGH_RISK_REQUEST_TYPES,
    INTENT_TO_REQUEST_TYPE,
    CaseFacts,
)
from app.domain.enums import (
    ComplaintRisk,
    CustomerIntent,
    DealerAuthorizationStatus,
    EmotionLevel,
    KnowledgeHitStatus,
    RequestType,
    WarrantyStatus,
)

# 同一必要事实连续澄清两轮仍无新增信息时停止重复追问（工程默认，可用案例校准）
MAX_CLARIFICATION_ATTEMPTS = 2

ROUTE_TROUBLESHOOTING = "troubleshooting"
ROUTE_WARRANTY_CHECK = "warranty_check"
ROUTE_REQUEST_DRAFT = "request_draft"
ROUTE_DEALER_VERIFICATION = "dealer_verification"
ROUTE_HUMAN_REVIEW = "human_review"
ROUTE_SCOPE_EXPLAIN = "scope_explain"


@dataclass
class RouteDecision:
    route: str
    allowed_actions: list[str]
    human_intervention_required: bool = False
    human_intervention_reason: str | None = None
    communication_style: str = "neutral"
    notes: list[str] = field(default_factory=list)


def communication_style_for(emotion: EmotionLevel) -> str:
    return {
        EmotionLevel.CALM: "direct",
        EmotionLevel.DISSATISFIED: "acknowledge_then_solve",
        EmotionLevel.ANGRY: "brief_reassure_then_solve",
        EmotionLevel.UNKNOWN: "neutral",
    }[emotion]


def decide_route(
    *,
    facts: CaseFacts,
    intents: list[CustomerIntent],
    emotion: EmotionLevel,
    complaint_risk: ComplaintRisk,
    knowledge_hit_status: KnowledgeHitStatus | None,
    warranty_status: WarrantyStatus | None = None,
    dealer_status: DealerAuthorizationStatus | None = None,
    clarification_attempts: int = 0,
    conflict_detected: bool = False,
) -> RouteDecision:
    """决定服务路径与当前允许的 Agent 动作。"""

    allowed: list[str] = []
    notes: list[str] = []
    style = communication_style_for(emotion)

    missing = facts.missing_required()
    if missing:
        # 关键事实缺失：先补问，不进入高风险办理
        allowed.append("ask_clarification")
        if knowledge_hit_status is not None:
            allowed.append("knowledge_search")
        if clarification_attempts >= MAX_CLARIFICATION_ATTEMPTS:
            notes.append(
                f"必要事实 {'、'.join(missing)} 已连续澄清 {clarification_attempts} 轮仍无新增信息，"
                "停止重复追问，转后台复核"
            )
            return RouteDecision(
                route=ROUTE_HUMAN_REVIEW,
                allowed_actions=allowed,
                human_intervention_required=True,
                human_intervention_reason="missing_required_facts_after_clarification",
                communication_style=style,
                notes=notes,
            )
        return RouteDecision(
            route=ROUTE_TROUBLESHOOTING,
            allowed_actions=allowed,
            communication_style=style,
            notes=notes,
        )

    # 依据缺失或冲突：先补查，仍无法确认才进后台（不是一次未命中就转人工）
    if knowledge_hit_status is KnowledgeHitStatus.NOT_FOUND:
        notes.append("未检索到适用依据，不编造结论；可补问或转后台复核")
        if any(intent in INTENT_TO_REQUEST_TYPE for intent in intents):
            return RouteDecision(
                route=ROUTE_HUMAN_REVIEW,
                allowed_actions=["knowledge_search", "ask_clarification"],
                human_intervention_required=True,
                human_intervention_reason="no_applicable_knowledge_for_high_risk_request",
                communication_style=style,
                notes=notes,
            )
        return RouteDecision(
            route=ROUTE_TROUBLESHOOTING,
            allowed_actions=["knowledge_search", "ask_clarification"],
            communication_style=style,
            notes=notes,
        )

    if knowledge_hit_status is KnowledgeHitStatus.CONFLICTING or conflict_detected:
        notes.append("知识或数据存在冲突，暂停高风险办理并进入人工确认")
        return RouteDecision(
            route=ROUTE_HUMAN_REVIEW,
            allowed_actions=["knowledge_search"],
            human_intervention_required=True,
            human_intervention_reason="conflicting_evidence",
            communication_style=style,
            notes=notes,
        )

    # 需要核验购买渠道的场景：第三方渠道或订单未命中
    needs_dealer_check = facts.purchase_channel in {"third_party_seller", "marketplace"} or (
        facts.seller_name_raw is not None and facts.order_id is None
    )
    if needs_dealer_check and dealer_status in {
        None,
        DealerAuthorizationStatus.UNKNOWN,
        DealerAuthorizationStatus.MULTIPLE_MATCHES,
        DealerAuthorizationStatus.QUERY_FAILED,
    }:
        allowed.append("dealer_lookup")
        allowed.append("ask_clarification")
        notes.append("需要核验实际购买渠道；已有信息不足时补问实际店铺或凭证")
        return RouteDecision(
            route=ROUTE_DEALER_VERIFICATION,
            allowed_actions=allowed,
            communication_style=style,
            notes=notes,
        )

    # 高风险诉求：生成草稿并进入人工确认
    high_risk_intents = [
        intent
        for intent in intents
        if INTENT_TO_REQUEST_TYPE.get(intent) in HIGH_RISK_REQUEST_TYPES
    ]
    if high_risk_intents:
        allowed.extend(
            [
                "knowledge_search",
                "order_lookup",
                "warranty_evaluate",
                "create_request_draft",
            ]
        )
        return RouteDecision(
            route=ROUTE_REQUEST_DRAFT,
            allowed_actions=allowed,
            # 草稿由 Agent 生成，但批准必须人工：这里不置 human_required，
            # 而是在草稿落库后由案件状态体现为待人工确认
            human_intervention_required=False,
            communication_style=style,
            notes=["将生成申请草稿并提交人工确认；批准不等于真实业务已完成"],
        )

    if CustomerIntent.WARRANTY_CHECK in intents:
        allowed.extend(["knowledge_search", "order_lookup", "warranty_evaluate"])
        # 质保查询失败必须记录为「查询失败」，不得等同于过保或非授权
        if warranty_status is WarrantyStatus.QUERY_FAILED:
            notes.append("质保查询失败：记录失败状态并允许重试，不得判定过保或非授权")
        return RouteDecision(
            route=ROUTE_WARRANTY_CHECK,
            allowed_actions=allowed,
            communication_style=style,
            notes=notes,
        )

    allowed.extend(["knowledge_search", "troubleshooting_plan", "order_lookup"])
    if warranty_status is WarrantyStatus.QUERY_FAILED:
        notes.append("质保查询失败：记录失败状态并允许重试，不得判定过保或非授权")
    return RouteDecision(
        route=ROUTE_TROUBLESHOOTING,
        allowed_actions=allowed,
        communication_style=style,
        notes=notes,
    )


def primary_request_type(intents: list[CustomerIntent]) -> RequestType | None:
    """按业务优先级选出主申请类型。"""

    priority = [
        CustomerIntent.REFUND,
        CustomerIntent.REPLACEMENT,
        CustomerIntent.REPAIR,
        CustomerIntent.PARTS,
    ]
    for intent in priority:
        if intent in intents:
            return INTENT_TO_REQUEST_TYPE[intent]
    return None


def sort_intents(intents: list[CustomerIntent]) -> list[CustomerIntent]:
    """多个意图无法排序时保留全部，但给出稳定顺序供展示。"""

    order = [
        CustomerIntent.COMPLAINT,
        CustomerIntent.REFUND,
        CustomerIntent.REPLACEMENT,
        CustomerIntent.REPAIR,
        CustomerIntent.PARTS,
        CustomerIntent.WARRANTY_CHECK,
        CustomerIntent.DIAGNOSIS,
        CustomerIntent.PROGRESS_CHECK,
        CustomerIntent.UNKNOWN,
    ]
    index = {intent: position for position, intent in enumerate(order)}
    return sorted(intents, key=lambda item: index.get(item, len(order)))
