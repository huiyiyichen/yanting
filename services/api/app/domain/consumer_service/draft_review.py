"""客服发送前质检（改进方案 P1-5）：纯规则，不调模型、不阻断发送。

高严重度（事实不符、医学判断）由前端在首次点击发送时拦一次，再次点击即发送。
"""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass

from app.schemas.base import ApiModel


class DraftFinding(ApiModel):
    kind: str
    severity: str
    label: str
    quote: str
    start: int
    end: int


@dataclass(frozen=True)
class Rule:
    kind: str
    severity: str
    label: str
    pattern: re.Pattern[str]
    negations: tuple[str, ...] = ()
    angry_only: bool = False


RULES = (
    Rule("unfounded_promise", "medium", "含无依据承诺",
         re.compile(r"保证|一定(?:会)?(?:到账|退|补|赔|解决|没问题)|马上(?:退|到账|补发|发)|肯定(?:没问题|能|会|可以)|百分百|绝对(?:没问题|不会)"),
         negations=("不能", "无法", "不敢", "没法", "不好")),
    Rule("medical", "high", "含医学判断",
         re.compile(r"就是过敏|只是过敏|不是过敏|没事的?(?:，|,)?(?:可以)?继续用|可以继续(?:使用|用)|不用(?:去)?就医|不需要就医|不用看医生|过(?:两|几)天就好"),
         negations=("建议", "请")),
    Rule("cold_tone", "medium", "语气可能激化",
         re.compile(r"按(?:照)?流程|请理解|系统规定|规定就是|没办法|您自己"),
         angry_only=True),
)
AMOUNT = re.compile(r"(?:¥|￥)\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*(?:元|块)")
IDENTIFIER = re.compile(r"(?<![\d])(\d{10,})(?![\d])|(?<![A-Za-z0-9])([A-Z]{1,3}\d{8,})(?![A-Za-z0-9])")


def _normal_amount(value: str) -> str:
    return f"{float(value):.2f}"


def review_draft(text: str, *, catalog: dict[str, set[str]], emotion: str | None) -> list[DraftFinding]:
    findings: list[DraftFinding] = []
    for rule in RULES:
        if rule.angry_only and emotion != "angry":
            continue
        for match in rule.pattern.finditer(text):
            window = text[max(0, match.start() - 6):match.start()]
            if any(word in window for word in rule.negations):
                continue
            findings.append(DraftFinding(kind=rule.kind, severity=rule.severity, label=rule.label,
                                         quote=match.group(0), start=match.start(), end=match.end()))
            break
    amounts = {_normal_amount(value) for value in catalog.get("amounts", set())}
    for match in AMOUNT.finditer(text):
        value = match.group(1) or match.group(2)
        if amounts and _normal_amount(value) not in amounts:
            findings.append(DraftFinding(kind="fact_mismatch", severity="high", label="金额与记录不符",
                                         quote=match.group(0), start=match.start(), end=match.end()))
            break
    ids = catalog.get("ids", set())
    for match in IDENTIFIER.finditer(text):
        value = match.group(1) or match.group(2)
        if value not in ids:
            findings.append(DraftFinding(kind="fact_mismatch", severity="high", label="编号与记录不符",
                                         quote=value, start=match.start(), end=match.end()))
            break
    return findings


AMOUNT_FIELDS = ("paidAmount", "unitPrice", "refundAmount")
ID_FIELDS = ("orderId", "workOrderId", "ticketId", "trackingNo", "originalTrackingNo",
             "reshipTrackingNo", "relatedTrackingNo", "refundId")


def source_catalog(sources) -> dict[str, set[str]]:
    """来源目录里的金额与编号：订单、源工单、本地跟进字段，以及会话原文中已出现的值。"""
    amounts: set[str] = set()
    ids: set[str] = set()
    for source in sources:
        fields = source.fields or {}
        for key in AMOUNT_FIELDS:
            if fields.get(key) not in (None, ""):
                with suppress(ValueError):
                    amounts.add(_normal_amount(str(fields[key])))
        for key in ID_FIELDS:
            if fields.get(key):
                ids.add(str(fields[key]))
        text = source.text or ""
        for match in AMOUNT.finditer(text):
            amounts.add(_normal_amount(match.group(1) or match.group(2)))
        for match in IDENTIFIER.finditer(text):
            ids.add(match.group(1) or match.group(2))
    return {"amounts": amounts, "ids": ids}


def review_conversation_draft(session, conversation_id: str, text: str) -> list[DraftFinding]:
    from app.domain.consumer_service.emotion import score_message
    from app.domain.consumer_service.grounding import collect_sources
    from app.domain.consumer_service.workspace import conversation_messages
    from app.repositories.consumer_service import ConsumerServiceRepository

    context = ConsumerServiceRepository(session).context(conversation_id)
    sources = collect_sources(session, conversation_id, context)
    latest = [m.body for m in conversation_messages(session, conversation_id)
              if m.sender_role.value == "customer" and m.body]
    emotion = {0: "calm", 1: "dissatisfied", 2: "angry"}.get(max(score_message(body) for body in latest[-3:])) if latest else None
    return review_draft(text, catalog=source_catalog(sources), emotion=emotion)
