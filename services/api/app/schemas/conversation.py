"""会话、消息与案件的 API 契约。

命名约定：API JSON 使用 `camelCase`，由 Pydantic 别名统一转换；
前端类型由 OpenAPI 生成，不手工复制。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.domain.enums import (
    CaseStatus,
    ComplaintRisk,
    ConversationStage,
    CustomerIntent,
    EmotionLevel,
    RatingStatus,
    RequestStatus,
    RequestType,
    SenderRole,
    ServiceMode,
)
from app.schemas.base import ApiModel


class CreateConversationRequest(ApiModel):
    customer_id: str = Field(default="CUST-DEMO-01", max_length=64)
    title: str | None = Field(default=None, max_length=200)


class ConversationSummary(ApiModel):
    conversation_id: str
    title: str
    customer_id: str
    service_mode: ServiceMode
    message_revision: int
    mode_revision: int
    last_message_preview: str = ""
    message_count: int = 0
    case_status: CaseStatus | None = None
    auto_reply_status: str = "idle"


class MessageView(ApiModel):
    """消息。发送方持久化记录，渲染方向由当前视角计算，数据本身不翻转。"""

    message_id: str
    conversation_id: str
    sender_role: SenderRole
    body: str
    message_revision: int
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str


class SendMessageRequest(ApiModel):
    body: str = Field(default="", max_length=4000)
    # 幂等键由客户端生成：重复提交不追加第二条消息
    client_message_key: str = Field(min_length=1, max_length=80)
    attachment_ids: list[str] = Field(default_factory=list)


class SendMessageResponse(ApiModel):
    message: MessageView
    created: bool
    reply: MessageView | None = None
    decision: AgentDecisionView | None = None


class CapabilityView(ApiModel):
    """客服可见的当前允许/禁止动作与不确定性标签。"""

    allowed_actions: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    uncertainty_flags: list[str] = Field(default_factory=list)


class AgentDecisionView(ApiModel):
    conversation_stage: ConversationStage
    service_route: str
    customer_intents: list[CustomerIntent] = Field(default_factory=list)
    emotion_level: EmotionLevel
    complaint_risk: ComplaintRisk
    missing_facts: list[str] = Field(default_factory=list)
    product_candidates: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_hit_status: str | None = None
    retrieval_id: str | None = None
    warranty_status: str | None = None
    dealer_authorization_status: str | None = None
    request_draft: dict[str, Any] | None = None
    human_intervention_required: bool = False
    human_intervention_reason: str | None = None
    case_status: CaseStatus
    rating_requested: bool = False
    notes: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    model_id: str | None = None
    prompt_version: str | None = None


class EvidenceView(ApiModel):
    """知识依据。只暴露来源定位与摘录，不暴露内部提示词或工具日志。"""

    retrieval_id: str
    snapshot_id: str
    chunk_id: str
    document_id: str
    document_title: str
    document_version: str
    knowledge_base_id: str
    visibility: str
    heading_path: str
    source_locator: str
    quoted_excerpt: str
    applicability: dict[str, Any] = Field(default_factory=dict)
    channel_ranks: dict[str, Any] = Field(default_factory=dict)
    rrf_score: float


class CaseView(ApiModel):
    """案件信息（客服侧）。客户侧不返回该结构。"""

    case_id: str
    conversation_id: str
    case_status: CaseStatus
    conversation_stage: ConversationStage
    product_id: str | None = None
    product_model: str | None = None
    product_category: str | None = None
    country_code: str | None = None
    purchase_channel: str | None = None
    seller_name_raw: str | None = None
    seller_name_standard: str | None = None
    customer_intents: list[CustomerIntent] = Field(default_factory=list)
    emotion_level: EmotionLevel
    complaint_risk: ComplaintRisk
    warranty_status: str | None = None
    dealer_authorization_status: str | None = None
    knowledge_hit_status: str | None = None
    retrieval_id: str | None = None
    troubleshooting_result: str
    rating_status: RatingStatus
    user_rating: int | None = None
    missing_facts: list[str] = Field(default_factory=list)
    #: 多模态从图片里确认到的**可见现象**（不含根因结论）；未配置多模态时恒为空
    observed_from_image: list[str] = Field(default_factory=list)
    evidence: list[EvidenceView] = Field(default_factory=list)
    requests: list[RequestView] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    service_started_at: str
    updated_at: str


class RequestView(ApiModel):
    request_id: str
    request_type: RequestType
    request_status: RequestStatus
    request_revision: int
    payload_hash: str
    summary: str = ""
    reviewer_role: str | None = None
    reviewed_at: str | None = None
    review_action: str | None = None
    review_reason: str | None = None
    created_at: str


class ReviewRequest(ApiModel):
    """人工确认。批准绑定申请内容版本；拒绝/退回必须给原因。"""

    action: str = Field(pattern="^(approve|reject|request_information)$")
    reason: str | None = Field(default=None, max_length=64)
    reason_text: str | None = Field(default=None, max_length=500)
    expected_revision: int | None = None
    expected_payload_hash: str | None = None


class QueueItem(ApiModel):
    conversation_id: str
    case_id: str | None = None
    title: str
    customer_id: str
    case_status: CaseStatus | None = None
    service_mode: ServiceMode
    emotion_level: EmotionLevel | None = None
    complaint_risk: ComplaintRisk | None = None
    pending_request_count: int = 0
    updated_at: str
    data_source: str = "demo"


class RatingRequest(ApiModel):
    action: str = Field(pattern="^(request|submit|skip)$")
    rating: int | None = Field(default=None, ge=1, le=5)


class RatingView(ApiModel):
    case_id: str
    rating_status: RatingStatus
    # 未评价/已跳过时必须为 null，不得填默认分
    user_rating: int | None = None


class ServiceModeRequest(ApiModel):
    mode: ServiceMode


class ServiceModeView(ApiModel):
    conversation_id: str
    service_mode: ServiceMode
    mode_revision: int


class SuggestionView(ApiModel):
    suggestion_id: str
    conversation_id: str
    message_revision: int
    variant: str
    variant_label: str
    body: str
    is_mock: bool
    expires: bool = False


class SuggestionSetView(ApiModel):
    conversation_id: str
    message_revision: int
    current_revision: int
    expires: bool
    is_mock: bool
    model_id: str
    items: list[SuggestionView] = Field(default_factory=list)


class SuggestionActionRequest(ApiModel):
    """采用或忽略候选。**采用只写草稿，不发送**。"""

    variant: str = Field(pattern="^(recommended|concise|reassuring)$")
    action: str = Field(pattern="^(adopt|ignore)$")


class AttachmentView(ApiModel):
    attachment_id: str
    conversation_id: str
    message_id: str | None = None
    mime_type: str
    byte_size: int
    width: int | None = None
    height: int | None = None
    sha256: str
    created_at: str


class VisionAvailabilityView(ApiModel):
    """图片能力的真实状态。未配置多模态时如实报告，不假装看懂图片。"""

    vision_configured: bool
    max_bytes: int
    allowed_mime_types: list[str]
    note: str
