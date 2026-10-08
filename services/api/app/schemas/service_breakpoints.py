from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.base import ApiModel
from app.schemas.grounding import WorkflowStep

BreakpointKind = Literal["repeated_question", "unmet_promise", "resolution_mismatch"]


class BreakpointCitation(ApiModel):
    source_ref: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=300)


class BreakpointCandidate(ApiModel):
    kind: BreakpointKind
    topic: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=400)
    evidence: list[BreakpointCitation] = Field(min_length=2, max_length=6)
    state_ref: str | None = None
    promise_ref: str | None = None
    order_id: str | None = None
    work_order_id: str | None = None


class BreakpointEvidence(BreakpointCitation):
    kind: str
    label: str
    occurred_at: str | None = None
    conversation_id: str | None = None


class ServiceBreakpointView(ApiModel):
    kind: BreakpointKind
    kind_label: str
    topic: str
    reason: str
    evidence: list[BreakpointEvidence]
    order_id: str | None = None
    work_order_id: str | None = None
    detected_at: str
    promise_due_at: str | None = None
    recommended_action: str


class ServiceBreakpointAssessmentView(ApiModel):
    conversation_id: str
    assessment_id: str | None = None
    analyzed: bool = False
    stale: bool = False
    revision: int = 0
    findings: list[ServiceBreakpointView] = Field(default_factory=list)
    model_id: str | None = None
    is_mock: bool = False
    updated_at: str | None = None
    workflow_steps: list[WorkflowStep] = Field(default_factory=list)
    model_usage: dict[str, Any] = Field(default_factory=dict)
