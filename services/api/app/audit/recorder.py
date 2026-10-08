"""追加式审计记录。

要求（PRD 第 4.6 节、工程规范第 7 节）：
- 审计事件**追加**写入，不被业务状态覆盖；
- 记录 `trace_id`、`conversation_id`、`case_id`、`actor_type`、模型与提示词版本、
  知识快照版本、`input_hash`、输出结构版本、工具名/请求 ID/状态、风险等级、
  人工确认状态与时间；
- **默认不保存完整原始 prompt/output**；
- 订单号、手机号、地址等使用掩码或哈希；
- 业务记录、运行日志和审计记录分开保存；
- 本期不存在人工超时事件，也不生成任何超时审计。
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.domain.case_state.models import AuditEventRow, new_id
from app.logging_setup import get_logger, log_event

logger = get_logger(__name__)

# 掩码规则：命中即整体替换，避免把敏感值写进审计
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_ORDER_RE = re.compile(r"\b(SO|PO|ORD)[-_]?\d{4}[-_]?\d{0,4}[-_]?\d{0,6}\b", re.IGNORECASE)
_ID_CARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_ADDRESS_HINTS = ("省", "市", "区", "街道", "路", "号", "小区", "栋", "室")


def hash_text(text: str) -> str:
    """计算输入哈希。审计只存哈希，不存原文。"""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mask_sensitive(text: str) -> str:
    """对文本做最小化脱敏。

    只处理高置信度模式（手机号、订单号、身份证、邮箱）；
    地址类没有可靠的通用模式，因此不做猜测式替换，
    而是在保存前由调用方只传摘要。
    """

    masked = _PHONE_RE.sub("[手机号已掩码]", text)
    masked = _ORDER_RE.sub("[订单号已掩码]", masked)
    masked = _ID_CARD_RE.sub("[证件号已掩码]", masked)
    masked = _EMAIL_RE.sub("[邮箱已掩码]", masked)
    return masked


def summarize(text: str, limit: int = 160) -> str:
    """生成可入库的摘要：先脱敏再截断。"""

    collapsed = " ".join(mask_sensitive(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


@dataclass(frozen=True, slots=True)
class AuditContext:
    """一次业务动作的审计上下文。`trace_id` 在一个用户轮次内保持不变。"""

    trace_id: str
    actor_type: str
    conversation_id: str | None = None
    case_id: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    knowledge_snapshot_version: str | None = None
    output_schema_version: str | None = None

    @staticmethod
    def new_turn(
        *,
        actor_type: str,
        conversation_id: str | None = None,
        case_id: str | None = None,
        **extra: Any,
    ) -> AuditContext:
        return AuditContext(
            trace_id=f"trace-{uuid.uuid4().hex[:12]}",
            actor_type=actor_type,
            conversation_id=conversation_id,
            case_id=case_id,
            **extra,
        )


class AuditRecorder:
    """把审计事件写入数据库。只追加，不更新、不删除。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        context: AuditContext,
        *,
        event_type: str,
        input_text: str | None = None,
        output_schema_version: str | None = None,
        tool_name: str | None = None,
        tool_request_id: str | None = None,
        tool_status: str | None = None,
        risk_level: str | None = None,
        human_confirmation_status: str | None = None,
        detail: dict[str, Any] | None = None,
        knowledge_snapshot_version: str | None = None,
    ) -> AuditEventRow:
        """写入一条审计事件。

        `input_text` 只用于计算哈希与生成脱敏摘要，**原文不入库**。
        """

        row = AuditEventRow(
            audit_event_id=new_id("aud"),
            trace_id=context.trace_id,
            conversation_id=context.conversation_id,
            case_id=context.case_id,
            actor_type=context.actor_type,
            event_type=event_type,
            model_provider=context.model_provider,
            model_name=context.model_name,
            model_version=context.model_version,
            prompt_version=context.prompt_version,
            knowledge_snapshot_version=(
                knowledge_snapshot_version or context.knowledge_snapshot_version
            ),
            input_hash=hash_text(input_text) if input_text else None,
            output_schema_version=output_schema_version or context.output_schema_version,
            tool_name=tool_name,
            tool_request_id=tool_request_id,
            tool_status=tool_status,
            risk_level=risk_level,
            human_confirmation_status=human_confirmation_status,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
            created_at=datetime.now(UTC),
        )
        self._session.add(row)
        self._session.flush()
        log_event(
            logger,
            "audit_recorded",
            trace_id=context.trace_id,
            event_type=event_type,
            tool_name=tool_name,
            tool_status=tool_status,
        )
        return row

    def record_model_call(
        self,
        context: AuditContext,
        *,
        input_text: str,
        latency_seconds: float,
        output_schema_version: str,
        is_mock: bool,
        detail: dict[str, Any] | None = None,
    ) -> AuditEventRow:
        """记录一次模型调用。不保存原始 prompt 与完整输出。"""

        return self.record(
            context,
            event_type="model_call",
            input_text=input_text,
            output_schema_version=output_schema_version,
            detail={
                "latencySeconds": round(latency_seconds, 3),
                "isMock": is_mock,
                **(detail or {}),
            },
        )

    def record_tool_calls(
        self,
        context: AuditContext,
        *,
        call_log: list[dict[str, Any]],
        knowledge_snapshot_version: str | None = None,
    ) -> int:
        """把 ToolGateway 的调用轨迹逐条写入审计。

        工具失败/超时也要记录（工程规范第 7 节）。
        """

        count = 0
        for item in call_log:
            message = str(item.get("message") or "")
            self.record(
                context,
                event_type="tool_call",
                input_text=json.dumps(item.get("arguments") or {}, ensure_ascii=False),
                tool_name=str(item.get("tool") or ""),
                tool_request_id=str(item.get("toolRequestId") or ""),
                tool_status=str(item.get("status") or ""),
                risk_level=str(item.get("riskLevel") or ""),
                knowledge_snapshot_version=knowledge_snapshot_version,
                detail={"message": summarize(message, limit=120)},
            )
            count += 1
        return count


def audit_event_payload(row: AuditEventRow) -> dict[str, Any]:
    """审计事件的对外结构。不返回 detail 中的原始文本。"""

    return {
        "auditEventId": row.audit_event_id,
        "traceId": row.trace_id,
        "conversationId": row.conversation_id,
        "caseId": row.case_id,
        "actorType": row.actor_type,
        "eventType": row.event_type,
        "modelProvider": row.model_provider,
        "modelName": row.model_name,
        "modelVersion": row.model_version,
        "promptVersion": row.prompt_version,
        "knowledgeSnapshotVersion": row.knowledge_snapshot_version,
        "inputHash": row.input_hash,
        "outputSchemaVersion": row.output_schema_version,
        "toolName": row.tool_name,
        "toolRequestId": row.tool_request_id,
        "toolStatus": row.tool_status,
        "riskLevel": row.risk_level,
        "humanConfirmationStatus": row.human_confirmation_status,
        "createdAt": row.created_at.isoformat(),
    }
