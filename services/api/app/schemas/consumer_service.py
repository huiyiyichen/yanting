"""客服可见的消费者服务轨迹契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.domain.enums import (
    EmotionLevel,
    EmotionTrend,
    ServiceMode,
    ServiceRiskLevel,
    ServiceRiskStatus,
    ServiceRiskType,
)
from app.schemas.base import ApiModel
from app.schemas.grounding import GroundingClaim, GroundingSource, MemoryItem, WorkflowStep
from app.schemas.service_breakpoints import ServiceBreakpointView


class ServiceOrderView(ApiModel):
    source_record_id: str
    order_id: str
    conversation_id: str
    buyer_alias: str
    sku: str | None = None
    product_name: str | None = None
    quantity: int | None = None
    unit_price_minor: int | None = None
    paid_amount_minor: int | None = None
    currency: str
    source_status: str | None = None
    ordered_at: str
    paid_at: str | None = None
    shipped_at: str | None = None
    carrier: str | None = None
    tracking_no: str | None = None
    province: str | None = None
    city: str | None = None
    gift: str | None = None
    buyer_note: str | None = None


class ServiceWorkOrderView(ApiModel):
    source_record_id: str
    work_order_id: str
    work_order_type: str
    conversation_id: str
    buyer_alias: str
    order_id: str | None = None
    source_status: str
    normalized_status: str
    handler: str | None = None
    created_at: str
    completed_at: str | None = None
    detail: dict[str, Any]


class ServiceMessageView(ApiModel):
    source_record_id: str
    message_id: str
    conversation_id: str
    sender_role: str
    sender: str | None = None
    body: str | None = None
    content_type: str
    image_ref: str | None = None
    order_id: str | None = None
    work_order_id: str | None = None


class ServiceTimelineEventView(ApiModel):
    event_id: str
    source_record_id: str
    entity_type: str
    event_type: str
    occurred_at: str
    message: ServiceMessageView | None = None
    order: ServiceOrderView | None = None
    work_order: ServiceWorkOrderView | None = None


class ServiceProductView(ApiModel):
    sku: str | None = None
    name: str
    unit_price_minor: int | None = None
    source_record_ids: list[str]


class ServiceNodeView(ApiModel):
    occurred_at: str
    kind: str
    title: str
    status: str | None = None
    source_record_id: str


class ConsumerHistoryView(ApiModel):
    conversation_id: str
    first_at: str | None = None
    last_at: str | None = None
    latest_customer_message: str = ""
    latest_staff_message: str = ""
    order_ids: list[str] = Field(default_factory=list)
    work_order_ids: list[str] = Field(default_factory=list)
    relation: Literal["same_order", "historical"] = "historical"
    same_topic: bool | None = None


class ConsumerServiceContextView(ApiModel):
    dataset_id: str
    batch_id: str
    conversation_id: str
    buyer_alias: str
    buyer_aliases: list[str]
    first_at: str | None = None
    last_at: str | None = None
    orders: list[ServiceOrderView]
    work_orders: list[ServiceWorkOrderView]
    timeline: list[ServiceTimelineEventView]
    products: list[ServiceProductView] = Field(default_factory=list)
    service_nodes: list[ServiceNodeView] = Field(default_factory=list)
    history_conversation_ids: list[str] = Field(default_factory=list)
    history_services: list[ConsumerHistoryView] = Field(default_factory=list)


class ReceptionItemView(ApiModel):
    conversation_id: str
    buyer_alias: str
    title: str
    preview: str
    updated_at: str
    data_source: str
    message_revision: int
    unread_count: int
    risk_level: str | None = None
    current_emotion: EmotionLevel | None = None
    active_risk_types: list[ServiceRiskType] = Field(default_factory=list)
    review_risk_types: list[ServiceRiskType] = Field(default_factory=list)
    service_mode: ServiceMode = ServiceMode.OPERATOR_ASSISTED
    mode_revision: int = 0
    auto_reply_status: str = "idle"
    handoff_reason: str | None = None


class ReceptionSnapshotView(ApiModel):
    items: list[ReceptionItemView]
    unread_total: int


class ReplyEmpathyDimension(ApiModel):
    key: Literal["emotion_response", "business_handling", "personalized"]
    label: str
    status: Literal["present", "missing"]
    reason: str


class AssistantReplySuggestionView(ApiModel):
    style: str
    body: str
    claims: list[GroundingClaim] = Field(default_factory=list)
    empathy_dimensions: list[ReplyEmpathyDimension] = Field(default_factory=list)


class PersonalizedAdviceEvidence(ApiModel):
    source_ref: str
    label: str
    quote: str
    kind: str


class PersonalizedAdviceView(ApiModel):
    category: Literal["routine", "makeup", "product_selection", "trial_safety"]
    title: str
    action: str
    rationale: str
    scope: Literal["general_consumer", "product_specific"] = "general_consumer"
    product_sku: str | None = None
    product_name: str | None = None
    evidence: list[PersonalizedAdviceEvidence] = Field(default_factory=list)
    claims: list[GroundingClaim] = Field(default_factory=list)


class ConsumerServiceAssistantView(ApiModel):
    observation_id: str
    dataset_id: str
    batch_id: str
    conversation_id: str
    current_question: str
    service_summary: str
    emotion_level: EmotionLevel
    emotion_trend: EmotionTrend
    risk_types: list[ServiceRiskType]
    risk_level: ServiceRiskLevel
    risk_status: ServiceRiskStatus
    risk_reason: str
    evidence_refs: list[str]
    missing_information: list[str]
    next_steps: list[str]
    reply_suggestions: list[AssistantReplySuggestionView]
    adopted_count: int = 0
    personalized_advice: list[PersonalizedAdviceView] = Field(default_factory=list)
    is_mock: bool
    model_id: str
    prompt_version: str
    input_hash: str = ""
    stale: bool = False
    knowledge_status: str = "not_found"
    knowledge_evidence: list[dict[str, Any]] = Field(default_factory=list)
    handoff_required: bool = False
    delivery_mode: str = "draft"
    memory_items: list[MemoryItem] = Field(default_factory=list)
    grounding_sources: list[GroundingSource] = Field(default_factory=list)
    verification_status: str = "unverified"
    workflow_steps: list[WorkflowStep] = Field(default_factory=list)
    model_usage: dict[str, Any] = Field(default_factory=dict)
    intent: str = "unknown"
    service_breakpoints: list[ServiceBreakpointView] | None = None


class AssistantActionRequest(ApiModel):
    input_hash: str
    style: str
    action: str = Field(pattern="^(adopt|ignore)$")


class RiskAlertView(ApiModel):
    alert_id: str
    conversation_id: str
    buyer_alias: str
    order_id: str | None = None
    work_order_id: str | None = None
    risk_type: ServiceRiskType
    risk_level: ServiceRiskLevel
    risk_status: ServiceRiskStatus
    trigger_summary: str
    evidence_refs: list[str]
    recommended_action: str
    created_at: str
    updated_at: str
    handled_by: str | None = None
    handled_at: str | None = None
    handled_note: str | None = None
    episode: int = 1
    revision: int = 1
    rule_version: str = "legacy"
    signal_active: bool = True
    current_attention: Literal["active", "review", "closed", "historical"] | None = None
    last_signal_at: str | None = None
    order_ids: list[str] = Field(default_factory=list)
    work_order_ids: list[str] = Field(default_factory=list)
    conditions: dict[str, Any] = Field(default_factory=dict)


class RiskAlertDetailView(ApiModel):
    alert: RiskAlertView
    service_context: ConsumerServiceContextView


class RiskAlertStatusRequest(ApiModel):
    status: ServiceRiskStatus
    note: str = ""
