"""AI 话术候选（客服辅助）。

要求（前端规范第 6.1 节、PRD 第 6.3 节）：
- 同一会话、同一最新上下文生成「推荐 / 简洁 / 安抚」三种**措辞**，
  事实与办理策略必须一致：不能一条说硬件故障、一条说软件故障；
- 不能凭空许诺赔付或联系工程师；
- 候选绑定 `(conversation_id, message_revision)`，新客户消息到达即过期；
- **采用 ≠ 发送**：采用只写入客服草稿，发送是独立动作；
- 生成失败不阻塞客服手动回复。

与真实模型的关系：候选必须来自真实模型；模型不可用时返回明确错误，
不静默替换为固定文案。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.agent.understanding import extract_json
from app.domain.case_state.models import AiSuggestionRow, CaseRow, ConversationRow, new_id
from app.errors import ModelOutputInvalid, ProviderNotConfigured
from app.integrations.model_provider import ChatMessage, ModelProvider
from app.logging_setup import get_logger, log_event

logger = get_logger(__name__)

SUGGESTION_PROMPT_VERSION = "s3-suggestions-v1"

VARIANTS = ("recommended", "concise", "reassuring")
VARIANT_LABELS = {
    "recommended": "推荐",
    "concise": "简洁",
    "reassuring": "安抚",
}

SYSTEM_PROMPT = """你是安克售后客服的回复起草助手。为客服起草回复措辞。

严格规则：
1. 只输出 JSON，不要解释文字、不要 markdown 代码块。
2. 三个版本必须是**同一事实、同一办理策略**的不同措辞，不能互相矛盾。
   不允许一条说硬件故障、另一条说是软件问题。
3. 不得承诺退款、赔付、金额、时限，不得声称已联系工程师或已安排上门。
   可以说明「已提交确认 / 正在核对 / 需要补充信息」。
4. 不得编造知识依据或引用不存在的政策。如需说明依据，只能转述给定的证据摘要。
5. 语气要求：
   - recommended：稳妥完整，先确认问题再说明下一步
   - concise：简短直接，1—2 句
   - reassuring：先回应情绪，再说明下一步
6. 每条 60—200 字，中文。

输出 JSON：
{"recommended": "...", "concise": "...", "reassuring": "..."}"""


class _Suggestions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recommended: str = Field(min_length=1)
    concise: str = Field(min_length=1)
    reassuring: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class SuggestionSet:
    conversation_id: str
    message_revision: int
    items: list[AiSuggestionRow]
    is_mock: bool
    model_id: str
    expires: bool


def _latest_customer_message(session: Session, conversation_id: str) -> str:
    from app.domain.case_state.models import MessageRow

    row = (
        session.execute(
            select(MessageRow)
            .where(MessageRow.conversation_id == conversation_id)
            .where(MessageRow.sender_role == "customer")
            .order_by(MessageRow.applies_to_message_revision.desc())
        )
        .scalars()
        .first()
    )
    return row.body if row else ""


def build_suggestion(
    session: Session,
    *,
    conversation: ConversationRow,
    case: CaseRow | None,
    provider: ModelProvider,
    knowledge_excerpts: list[str] | None = None,
) -> SuggestionSet:
    """生成三种措辞的候选并落库。"""

    if not provider.available():
        raise ProviderNotConfigured(
            "文本模型未配置，无法生成话术候选",
            detail="候选必须来自真实模型；不提供预设文案兜底",
        )

    latest = _latest_customer_message(session, conversation.conversation_id)
    context_lines = [
        f"客户最新消息：{latest or '（尚无客户消息）'}",
    ]
    if case is not None:
        context_lines.append(
            "案件事实："
            + json.dumps(
                {
                    "产品型号": case.product_model,
                    "国家地区": case.country_code,
                    "客户意图": case.customer_intents_json,
                    "情绪": case.emotion_level,
                    "投诉风险": case.complaint_risk,
                    "质保状态": case.warranty_status,
                    "待补充": case.missing_facts_json,
                },
                ensure_ascii=False,
            )
        )
    if knowledge_excerpts:
        joined = " | ".join(item[:200] for item in knowledge_excerpts[:3])
        context_lines.append(f"可用依据摘要（只能转述，不得新增）：{joined}")

    result = provider.complete(
        [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content="\n".join(context_lines)),
        ],
        temperature=0.4,
        max_tokens=900,
        json_mode=True,
    )

    payload = extract_json(result.text)
    try:
        parsed = _Suggestions.model_validate(payload)
    except ValidationError as exc:
        raise ModelOutputInvalid("话术候选输出不符合结构契约", detail=str(exc)[:500]) from exc

    bodies = {
        "recommended": parsed.recommended.strip(),
        "concise": parsed.concise.strip(),
        "reassuring": parsed.reassuring.strip(),
    }
    for variant, body in bodies.items():
        if not body:
            raise ModelOutputInvalid(f"话术候选 {variant} 为空")

    # 旧候选标记为已过期（不删除，保留可追溯），并写入新候选
    revision = conversation.message_revision
    for row in session.execute(
        select(AiSuggestionRow).where(
            AiSuggestionRow.conversation_id == conversation.conversation_id
        )
    ).scalars():
        # 用 created_at 之外的方式表达过期：这里直接删除未采用的旧候选，
        # 已被采用/忽略的记录保留，便于复盘"客服是否用过候选"
        if row.adopted_at is None and row.ignored_at is None:
            session.delete(row)

    items: list[AiSuggestionRow] = []
    for variant in VARIANTS:
        row = AiSuggestionRow(
            suggestion_id=new_id("sug"),
            conversation_id=conversation.conversation_id,
            message_revision=revision,
            variant=variant,
            body=bodies[variant],
            generated_by="agent",
            model_id=result.model,
            is_mock=result.is_mock,
        )
        session.add(row)
        items.append(row)
    session.flush()

    log_event(
        logger,
        "suggestions_generated",
        conversation_id=conversation.conversation_id,
        message_revision=revision,
        is_mock=result.is_mock,
    )
    return SuggestionSet(
        conversation_id=conversation.conversation_id,
        message_revision=revision,
        items=items,
        is_mock=result.is_mock,
        model_id=result.model,
        expires=False,
    )


def list_suggestions(session: Session, conversation_id: str) -> SuggestionSet | None:
    """读取当前会话的候选，并标注是否已过期（有更新消息到达）。"""

    conversation = session.get(ConversationRow, conversation_id)
    if conversation is None:
        return None
    rows = list(
        session.execute(
            select(AiSuggestionRow)
            .where(AiSuggestionRow.conversation_id == conversation_id)
            .order_by(AiSuggestionRow.message_revision.desc(), AiSuggestionRow.created_at.asc())
        ).scalars()
    )
    if not rows:
        return None
    latest_revision = max(row.message_revision for row in rows)
    current = [row for row in rows if row.message_revision == latest_revision]
    return SuggestionSet(
        conversation_id=conversation_id,
        message_revision=latest_revision,
        items=current,
        is_mock=any(row.is_mock for row in current),
        model_id=current[0].model_id or "",
        # 新消息到达后旧候选过期，不得静默发送
        expires=latest_revision != conversation.message_revision,
    )


def mark_action(
    session: Session, *, conversation_id: str, variant: str, action: str
) -> AiSuggestionRow:
    """记录「采用」或「忽略」。

    **采用只写草稿，不发送**；这里只记录动作，不产生任何消息。
    """

    from datetime import datetime

    from app.errors import NotFoundError, ValidationRejected

    if action not in {"adopt", "ignore"}:
        raise ValidationRejected(f"未知的候选动作：{action}")

    row = (
        session.execute(
            select(AiSuggestionRow)
            .where(AiSuggestionRow.conversation_id == conversation_id)
            .where(AiSuggestionRow.variant == variant)
            .order_by(AiSuggestionRow.created_at.desc())
        )
        .scalars()
        .first()
    )
    if row is None:
        raise NotFoundError(f"未找到候选：{conversation_id}/{variant}")

    if action == "adopt":
        row.adopted_at = datetime.now(UTC)
    else:
        row.ignored_at = datetime.now(UTC)
    session.flush()
    return row


def suggestions_allowed_for_agent() -> dict[str, Any]:
    """候选的能力边界，供前端提示与审计使用。"""

    return {
        "variants": list(VARIANTS),
        "labels": VARIANT_LABELS,
        "adoptDoesNotSend": True,
        "requiresTakeoverToSend": True,
        "promptVersion": SUGGESTION_PROMPT_VERSION,
    }
