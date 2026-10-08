"""工具请求/返回的通用契约。

`ToolResult` 的关键要求（工程规范第 5.3 节）：
- 工具失败、超时、无权限和空结果必须使用**不同状态**；
- 模型不得伪造工具返回结果；
- 每次请求都有 `tool_request_id` 与幂等键。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.enums import ToolName

ToolResultStatusLiteral = Literal[
    "ok", "empty", "not_found", "timeout", "failed", "denied", "invalid_argument", "conflict"
]


@dataclass(frozen=True, slots=True)
class ToolContext:
    read_only: bool = True
    case_id: str | None = None
    conversation_id: str | None = None
    trace_id: str | None = None
    requested_by: str = "agent"


@dataclass(frozen=True, slots=True)
class ToolRequest:
    tool: ToolName
    arguments: dict[str, Any]
    tool_request_id: str = field(default_factory=lambda: f"treq-{uuid.uuid4().hex[:12]}")
    idempotency_key: str | None = None
    context: ToolContext = field(default_factory=ToolContext)


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool: ToolName
    status: ToolResultStatusLiteral
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    tool_request_id: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @classmethod
    def error(
        cls,
        tool: ToolName,
        status: ToolResultStatusLiteral,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> ToolResult:
        return cls(tool=tool, status=status, data=data or {}, message=message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "tool": self.tool.value,
            "status": self.status,
            "message": self.message,
            "data": self.data,
            "toolRequestId": self.tool_request_id,
        }
