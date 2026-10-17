from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.base import ApiModel


class VerificationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    category: Literal["fact", "citation", "safety", "style"] = "fact"
    reply_index: int | None = Field(default=None, alias="replyIndex", ge=0)
    segment_index: int | None = Field(default=None, alias="segmentIndex", ge=0)
    source_id: str | None = Field(default=None, alias="sourceId")
    #: 问题所在字段；reply 以外的字段（摘要、记忆等）出错只撤下该字段，不影响回复建议
    field: Literal["reply", "service_summary", "memory", "next_steps", "advice", "breakpoints"] | None = None
    detail: str = Field(min_length=1, max_length=500)
    format_error: bool = Field(default=False, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_issue(cls, value):
        if isinstance(value, str):
            return {"category": "fact", "detail": value, "format_error": True}
        if isinstance(value, dict) and value.get("field") not in {
            None, "reply", "service_summary", "memory", "next_steps", "advice", "breakpoints",
        }:
            value = {**value, "field": None}
        if isinstance(value, dict) and value.get("category") not in {"fact", "citation", "safety", "style"}:
            return {**value, "category": "fact", "format_error": True}
        return value


class Verification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: bool
    issues: list[VerificationIssue] = Field(default_factory=list, max_length=8)

    @property
    def blocking_issues(self) -> list[VerificationIssue]:
        issues = [issue for issue in self.issues if issue.category != "style"]
        if not self.supported and not self.issues:
            return [VerificationIssue(detail="核验结果缺少具体依据", format_error=True)]
        return issues


class GroundingSource(ApiModel):
    source_id: str
    kind: Literal["order", "work_order", "followup", "customer_message", "staff_message", "knowledge", "image_observation"]
    subject_id: str
    label: str
    text: str
    occurred_at: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    #: 官方 Excel 行（service_source_record.record_id）；订单、源工单、导入聊天才有（追溯 T5）
    source_record_id: str | None = None

    def prompt_dump(self) -> dict[str, Any]:
        """Catalog entry for model prompts: the official row id is for tracing, not citing."""
        return self.model_dump(by_alias=True, mode="json", exclude={"source_record_id"})


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
