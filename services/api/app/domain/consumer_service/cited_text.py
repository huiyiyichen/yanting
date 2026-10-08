"""Convert model-selected, cited text parts to the existing presentation contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.grounding import GroundingClaim

ReplyStyle = Literal["recommended", "concise", "reassuring"]


class CitedText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=100)
    source_refs: list[str] = Field(default_factory=list, max_length=10)


class ActionText(CitedText):
    text: str = Field(min_length=1, max_length=80)


class ReasonText(CitedText):
    text: str = Field(min_length=1, max_length=60)


class SegmentedReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: ReplyStyle
    segments: list[CitedText] = Field(min_length=1, max_length=8)


def render_parts(parts: list[CitedText]) -> tuple[str, list[GroundingClaim]]:
    """No fact lookup or reference inference: use only the model's chosen refs."""
    return (
        "".join(part.text for part in parts),
        [GroundingClaim(text=part.text, source_refs=part.source_refs)
         for part in parts if part.source_refs],
    )
