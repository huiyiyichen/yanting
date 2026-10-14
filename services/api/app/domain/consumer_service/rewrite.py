"""回复改写（改进方案 P1-3）。

改写只调整语气、长度和措辞：用快速模型生成，再用程序校验保真——硬事实（数字、编号、金额、日期）
必须原样保留且不得新增；不得新增成分功效、状态或商品身份断言；不得引入无依据承诺或医学判断。
未通过时不替换原文。
"""

from __future__ import annotations

import json
import re

from app.domain.consumer_service.draft_review import review_draft
from app.domain.consumer_service.verification_policy import _EFFICACY, _PRODUCT, _STATUS
from app.schemas.base import ApiModel

INSTRUCTIONS = {
    "gentler": "更温和：多一点共情和安抚，语气柔和",
    "concise": "更简洁：保留全部事实，删去重复和客套，尽量一两句",
    "professional": "更专业：措辞规范清楚，少用语气词",
}
REWRITE_PROMPT = """你是美妆电商客服回复的改写助手。只改写语气、长度与措辞，不增删任何事实。
必须原样保留原文中的所有数字、订单号、金额、日期和商品名称；不得新增任何数字、承诺、成分功效或医学判断。
只输出JSON：{"text":"改写后的回复"}。"""
FACT = re.compile(r"[A-Za-z]*\d+(?:\.\d+)?")


class RewriteRequest(ApiModel):
    style: str
    text: str
    instruction: str


class RewriteView(ApiModel):
    style: str
    text: str
    instruction: str
    model: str


def _facts(text: str) -> set[str]:
    return set(FACT.findall(text))


def _signals(pattern: re.Pattern[str], text: str) -> set[str]:
    return set(pattern.findall(text))


def rewrite_issues(original: str, rewritten: str) -> list[str]:
    text = rewritten.strip()
    if not text:
        return ["改写结果为空"]
    if len(text) > 800:
        return ["改写结果过长"]
    if text == original.strip():
        return ["改写没有变化"]
    issues = []
    before, after = _facts(original), _facts(text)
    if before - after:
        issues.append("改写删去了原文事实：" + "、".join(sorted(before - after)))
    if after - before:
        issues.append("改写新增了原文没有的数字或编号：" + "、".join(sorted(after - before)))
    for label, pattern in (("成分功效", _EFFICACY), ("状态", _STATUS), ("商品", _PRODUCT)):
        if _signals(pattern, text) - _signals(pattern, original):
            issues.append(f"改写新增了{label}表述")
    old_kinds = {item.kind for item in review_draft(original, catalog={}, emotion=None)}
    for item in review_draft(text, catalog={}, emotion=None):
        if item.kind in {"unfounded_promise", "medical"} and item.kind not in old_kinds:
            issues.append(item.label)
    return issues


def rewrite_reply(provider, original: str, instruction: str) -> tuple[str, str]:
    from app.errors import ModelOutputInvalid
    from app.integrations.model_provider import ChatMessage

    result = provider.complete([
        ChatMessage(role="system", content=REWRITE_PROMPT),
        ChatMessage(role="user", content=json.dumps(
            {"instruction": INSTRUCTIONS[instruction], "text": original}, ensure_ascii=False)),
    ], temperature=0.3, max_tokens=600, json_mode=True, model_tier="fast")
    try:
        text = str(json.loads(result.text)["text"]).strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise ModelOutputInvalid("改写结果格式无效，已保留原文") from exc
    return text, result.model
