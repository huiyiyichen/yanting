from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field

from app.schemas.base import ApiModel
from app.schemas.consumer_service import ConsumerServiceContextView, RiskAlertView
from app.schemas.service_breakpoints import ServiceBreakpointAssessmentView

TicketStatus = Literal["pending", "in_progress", "waiting_customer", "waiting_internal", "resolved"]
TicketPriority = Literal["low", "normal", "high", "urgent"]
TicketType = Literal[
    "reship_exchange", "offline_payment", "logistics", "adverse_reaction", "return_refund"
]


class DemoOperatorView(ApiModel):
    operator_id: str
    name: str


class DemoOperatorRosterView(ApiModel):
    default_operator_id: str
    operators: list[DemoOperatorView]


class ReshipTicketDetail(ApiModel):
    kind: Literal["reship_exchange"]
    resolution: Literal["reship", "exchange"] = "reship"
    reason: str = Field(min_length=1, max_length=500)
    product_name: str = Field(default="", max_length=200)
    sku: str = Field(default="", max_length=80)
    quantity: int = Field(default=1, ge=1, le=999)


class PaymentTicketDetail(ApiModel):
    kind: Literal["offline_payment"]
    payment_type: Literal["refund", "price_adjustment", "compensation"]
    requested_amount: Decimal = Field(ge=0, le=100000, max_digits=8, decimal_places=2)
    reason: str = Field(min_length=1, max_length=500)


class LogisticsTicketDetail(ApiModel):
    kind: Literal["logistics"]
    issue_type: Literal["tracking_query", "stalled", "not_received", "damaged", "address_review"]
    reason: str = Field(min_length=1, max_length=500)
    carrier: str = Field(default="", max_length=80)
    tracking_no: str = Field(default="", max_length=80)


class ReactionTicketDetail(ApiModel):
    kind: Literal["adverse_reaction"]
    symptom_description: str = Field(min_length=1, max_length=500)
    affected_area: str = Field(default="", max_length=80)
    onset_interval: str = Field(default="", max_length=80)
    product_batch_no: str = Field(default="", max_length=80)
    stopped_use: Literal["yes", "no", "unknown"] = "unknown"
    sought_medical_care: Literal["yes", "no", "unknown"] = "unknown"


class ReturnTicketDetail(ApiModel):
    kind: Literal["return_refund"]
    request_type: Literal["return_refund", "refund_only"] = "return_refund"
    return_reason: str = Field(min_length=1, max_length=500)
    parcel_type: Literal["original", "reship", "unknown"] = "unknown"


TicketDetail = Annotated[
    ReshipTicketDetail | PaymentTicketDetail | LogisticsTicketDetail | ReactionTicketDetail | ReturnTicketDetail,
    Field(discriminator="kind"),
]


class TicketEventView(ApiModel):
    event_id: str
    actor: str
    action: str
    note: str
    created_at: str


class TicketView(ApiModel):
    ticket_id: str
    title: str
    conversation_id: str
    buyer_alias: str
    order_id: str | None = None
    work_order_type: TicketType
    source_status: str | None = None
    source_record_id: str | None = None
    status: TicketStatus
    priority: TicketPriority
    assignee: str
    due_at: str | None = None
    created_at: str
    updated_at: str
    revision: int
    detail: dict[str, object] = Field(default_factory=dict)
    local_detail: TicketDetail | None = None
    events: list[TicketEventView] = Field(default_factory=list)


class TicketCreateRequest(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    conversation_id: str
    order_id: str | None = None
    work_order_type: TicketType
    priority: TicketPriority = "normal"
    assignee: str = Field(default="", max_length=80)
    due_at: str | None = None
    note: str = Field(min_length=1, max_length=2000)
    local_detail: TicketDetail | None = None


class TicketUpdateRequest(ApiModel):
    expected_revision: int = Field(ge=0)
    status: TicketStatus
    priority: TicketPriority
    assignee: str = Field(max_length=80)
    due_at: str | None = None
    note: str = Field(min_length=1, max_length=2000)
    local_detail: TicketDetail | None = None


class RiskEvidenceView(ApiModel):
    ref: str
    kind: str
    label: str
    body: str
    occurred_at: str | None = None
    conversation_id: str | None = None


RiskJudgmentVerdict = Literal["confirmed", "false_positive", "insufficient"]


class RiskJudgmentView(ApiModel):
    judgment_id: str
    alert_id: str
    episode: int
    verdict: RiskJudgmentVerdict
    actor: str
    note: str
    detection_hash: str
    created_at: str
    stale: bool
    supersedes_id: str | None = None
    risk_type: str
    risk_level: str
    rule_version: str
    trigger_summary: str
    conversation_id: str
    order_ids: list[str]
    work_order_ids: list[str]
    evidence_refs: list[str]
    conditions: dict[str, object]
    signal_active: bool
    evidence: list[RiskEvidenceView] = Field(default_factory=list)


class RiskJudgmentRequest(ApiModel):
    verdict: RiskJudgmentVerdict
    note: str = Field(min_length=1, max_length=2000)
    expected_version: str = Field(min_length=1)
    expected_judgment_id: str | None = None


class RiskJudgmentExportView(ApiModel):
    format_version: Literal["loreal-risk-judgments-v1"] = "loreal-risk-judgments-v1"
    generated_at: str
    batch_id: str | None
    annotation_scope: Literal["demo_operator"] = "demo_operator"
    sampling_scope: Literal["detected_signals_only"] = "detected_signals_only"
    independently_validated: Literal[False] = False
    judgments: list[RiskJudgmentView]


class RiskIncidentView(ApiModel):
    incident_id: str
    buyer_alias: str
    conversation_ids: list[str]
    primary_conversation_id: str | None = None
    order_ids: list[str]
    work_order_ids: list[str]
    risk_level: str
    risk_status: str
    signals: list[RiskAlertView]
    latest_message: str
    updated_at: str
    recommended_action: str
    open_ticket_count: int
    needs_review: bool
    recurrence_count: int = 0
    historical_sensitivity: int = Field(default=0, ge=0, le=3)
    signal_active: bool = True
    version: str = ""
    judgments: list[RiskJudgmentView] = Field(default_factory=list)
    triage_score: int = Field(ge=0, le=100)
    triage_label: Literal["urgent", "priority", "review", "normal"]
    triage_reasons: list[str] = Field(default_factory=list)
    attention_state: Literal["active", "review", "closed"]
    current_emotion: Literal["calm", "dissatisfied", "angry", "unknown"]
    emotion_trend: Literal["stable", "rising", "falling", "repeated", "unknown"] = "unknown"
    service_state: Literal["live", "closed", "historical"] = "historical"
    service_closed_at: str | None = None
    latest_customer_at: str | None = None
    current_action: Literal["intervene", "review", "record_only", "none"] = "none"


class RiskIncidentDetailView(ApiModel):
    incident: RiskIncidentView
    contexts: list[ConsumerServiceContextView]
    evidence: list[RiskEvidenceView]
    tickets: list[TicketView]
    handling_history: list[TicketEventView]
    episodes: list[RiskEpisodeView] = Field(default_factory=list)
    service_breakpoint_assessments: list[ServiceBreakpointAssessmentView] = Field(default_factory=list)
    judgment_history: list[RiskJudgmentView] = Field(default_factory=list)
    contact_history: list[RiskEvidenceView] = Field(default_factory=list)
    emotion_history: list[RiskEmotionView] = Field(default_factory=list)
    service_points: list[RiskServicePointView] = Field(default_factory=list)
    emotion_comparisons: list[RiskEmotionComparisonView] = Field(default_factory=list)


class RiskEmotionView(ApiModel):
    message_id: str
    conversation_id: str
    occurred_at: str
    body: str
    emotion: Literal["calm", "dissatisfied", "angry"]
    trigger_factors: list[str] = Field(default_factory=list)


class RiskServicePointView(ApiModel):
    message_id: str
    conversation_id: str
    occurred_at: str
    body: str
    sender_role: Literal["operator", "assistant"]


class RiskEmotionComparisonView(ApiModel):
    conversation_id: str
    points: list[RiskEmotionView] = Field(default_factory=list)


class RiskEpisodeView(ApiModel):
    alert_id: str
    episode: int
    risk_type: str
    risk_level: str
    status: str
    closed_at: str
    handled_by: str | None = None
    handled_note: str | None = None
    evidence: list[RiskEvidenceView]
    rule_version: str


class RiskIncidentStatusRequest(ApiModel):
    status: Literal["in_progress", "resolved", "ignored", "reopen"]
    note: str = Field(min_length=1, max_length=2000)
    expected_version: str = Field(min_length=1)


class RiskInterventionRequest(ApiModel):
    conversation_id: str = Field(min_length=1)
    expected_version: str = Field(min_length=1)


class RiskScanView(ApiModel):
    alerts_created: int
    incident_count: int
    reference_time: str | None = None


class ReceptionStatsView(ApiModel):
    live_conversations: int
    historical_conversations: int
    unread_messages: int
    open_tickets: int
    pending_risks: int
