from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from app.schemas.base import ApiModel


class GroundingSource(ApiModel):
    source_id: str
    kind: Literal["order", "work_order", "followup", "customer_message", "staff_message", "knowledge", "image_observation"]
    subject_id: str
    label: str
    text: str
    occurred_at: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class MemoryItem(ApiModel):
    category: Literal["known", "concern", "attempted", "unresolved"]
    source_ref: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=300)
    label: str = Field(default="", max_length=40)


class GroundingClaim(ApiModel):
    text: str = Field(min_length=1, max_length=800)
    source_refs: list[str] = Field(min_length=1, max_length=10)


class WorkflowStep(ApiModel):
    name: str
    status: str
    duration_ms: int
    attempt: int = 1
    issues: list[str] = Field(default_factory=list, max_length=8)


class ServiceMemoryView(ApiModel):
    conversation_id: str
    revision: int = 0
    stale: bool = False
    items: list[MemoryItem] = Field(default_factory=list)
    sources: list[GroundingSource] = Field(default_factory=list)
    updated_at: str | None = None
    verified: bool = False
