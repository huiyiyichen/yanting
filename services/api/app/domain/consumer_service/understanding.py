"""意图与情绪 Agent（多 Agent 阶段 5 之后：从起草里拆出）。

只在 orchestration=multi 时运行，和取证 Worker 并行，结果交给起草与后续闸门使用：
起草不再自己判断 intent / emotion_level，而是直接采用本 Agent 的结论。

成本策略 U1「规则优先，拿不准才问模型」：
- 规则（分诊同一套词表）能明确判断时，直接返回，不调模型；
- 只有下面几种拿不准的情况才调用快速档模型，输入只有最近几条消费者原话（不带订单、知识）：
  U1a 规则判断不出意图（且不是寒暄）；
  U1b 同时出现商品问题和售后/物流诉求（混合意图）；
  U1c 当前这句没有情绪词，但上文有（情绪可能已经缓和，也可能还在）；
  U1d 出现反讽、阴阳怪气等词表抓不住的表达；
  U1e 只提到商品名（面霜、口红……）而没有咨询点，诉求不明。

防幻觉 U2：模型给出的情绪依据必须逐字出现在消费者原话里，否则情绪退回规则结论。
安全底线 U3：当前这句有明确的投诉/曝光信号时，情绪至少是 angry、意图为 complaint（除非是不良反应），
模型不能把它判低，避免漏掉风险。
模型失败、超时或输出不合格时一律退回规则结论，回复链路照常进行。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from app.domain.consumer_service.emotion import (
    ANGRY,
    DISSATISFIED,
    has_complaint_signal,
    score_message,
)

UNDERSTAND_VERSION = "YT_UNDERSTAND@1"
UNDERSTAND_PROMPT_CODE = "CUSTOMER_UNDERSTANDING_V1"

INTENTS = (
    "product_question", "order_status", "logistics", "refund", "return", "replacement",
    "adverse_reaction", "complaint", "other",
)
EMOTIONS = ("calm", "dissatisfied", "angry")
INTENT_TEXT = {
    "product_question": "商品咨询", "order_status": "订单进度", "logistics": "物流查询", "refund": "退款",
    "return": "退货", "replacement": "补发/换货", "adverse_reaction": "皮肤不适", "complaint": "投诉", "other": "其他",
}
EMOTION_TEXT = {"calm": "平稳", "dissatisfied": "不满", "angry": "愤怒"}
_EMOTION_OF = {ANGRY: "angry", DISSATISFIED: "dissatisfied"}
_RANK = {"calm": 0, "dissatisfied": 1, "angry": 2}

_AFTER_SALES = {"refund", "return", "replacement", "logistics", "order_status"}
#: 商品“咨询点”（成分、用法、适配……）。只提到商品名而没有咨询点时，诉求不明，不算商品咨询
_ASPECT = re.compile(
    r"成分|功效|效果|用法|怎么用|如何用|用量|顺序|搭配|适合|适用|肤质|敏感肌|油皮|干皮|混油|美白|抗老|保湿|防晒|色号|"
    r"质地|味道|香味|孕妇|哺乳|保质期|有效期|开封|真假|正品|批次|区别|推荐|哪款|什么商品|这是什么|能用|可以用|比"
)
#: 词表抓不住的反讽 / 阴阳怪气 / 隐含不满
_SARCASM = re.compile(r"呵呵|真行|真棒啊|厉害了|好得很|谢谢你们啊|服务真好啊|真是醉了|醉了|绝了|笑死|佩服|一次比一次|"
                      r"又是这样|每次都|还要我等|等了[一二三四五六七八九十两\d]+[天周]|多少天了|几天了")
_SMALL_TALK = re.compile(r"^(在吗|在不在|你好|您好|hi|hello|哈喽|谢谢|多谢|感谢|好的|好|嗯|嗯嗯|ok|收到|知道了|行)[!！。.~～?？\s]*$",
                         re.IGNORECASE)

UNDERSTAND_SYSTEM = (
    UNDERSTAND_PROMPT_CODE + "\n"
    "你是美妆电商客服系统里的「意图与情绪」判断环节。只根据消费者原话判断，不回复消费者。\n"
    "intent（当前这句最主要的业务诉求，单选）：\n"
    "- product_question 商品咨询：成分、功效、用法、肤质适配、真假、选购\n"
    "- order_status 订单状态：下单、取消、改地址、发票、价格核对\n"
    "- logistics 物流：发货、到哪了、没收到、签收\n"
    "- refund 退款：退款进度、到账、仅退款\n"
    "- return 退货\n"
    "- replacement 换货、补发、漏发少发、破损重发\n"
    "- adverse_reaction 使用后皮肤不适：过敏、红肿、刺痛、起疹（优先于其他意图）\n"
    "- complaint 明确要投诉、曝光、找12315、差评，且没有更具体的业务诉求\n"
    "- other 寒暄、致谢、闲聊、无法归类\n"
    "emotion_level（消费者此刻的情绪，结合上文）：\n"
    "- calm 平稳，包括礼貌催问\n"
    "- dissatisfied 不满、着急、失望、抱怨、反讽\n"
    "- angry 愤怒、威胁投诉/曝光、辱骂\n"
    "evidence：支撑情绪判断的一小段原话（必须逐字摘自消费者消息；情绪为 calm 时可为空字符串）。\n"
    '只输出 JSON：{"intent": "...", "emotion_level": "...", "evidence": "..."}'
)


@dataclass
class Understanding:
    intent: str = "other"
    emotion_level: str = "calm"
    #: rule：规则直接判定；model：模型判定；rule_fallback：模型失败退回规则
    source: str = "rule"
    evidence: str = ""
    #: 为什么需要（或不需要）调用模型，U1a–U1d / U2 / U3
    reasons: list[str] = field(default_factory=list)
    rule_intent: str = "other"
    rule_emotion: str = "calm"
    version: str = UNDERSTAND_VERSION

    def dump(self) -> dict:
        return asdict(self)

    def prompt_dump(self) -> dict:
        return {"intent": self.intent, "emotionLevel": self.emotion_level, "evidence": self.evidence,
                "source": self.source}


@dataclass
class RuleJudgment:
    intent: str
    emotion: str
    uncertain: list[str]
    complaint: bool


def _rule_intents(text: str) -> list[str]:
    from app.domain.consumer_service.triage import _INTENT_RULES

    return [intent for intent, pattern in _INTENT_RULES if pattern.search(text)]


def rule_judgment(latest: str, recent: list[str]) -> RuleJudgment:
    """规则判断，并列出拿不准的理由（为空表示规则可以直接给结论）。"""
    text = (latest or "").strip()
    window = [m for m in recent[-2:] if m]
    matched = _rule_intents(text)
    complaint = has_complaint_signal(text)
    uncertain: list[str] = []
    if matched:
        intent = matched[0]
        aspect = bool(_ASPECT.search(text))
        if "product_question" in matched and aspect and _AFTER_SALES & set(matched) and intent != "adverse_reaction":
            uncertain.append("U1b 同时出现商品问题和售后/物流诉求")
        elif matched == ["product_question"] and not aspect:
            uncertain.append("U1e 只提到商品名，诉求不明")
    elif complaint:
        intent = "complaint"
    elif _SMALL_TALK.match(text):
        intent = "other"
    else:
        intent = "other"
        uncertain.append("U1a 规则判断不出意图")
    current = score_message(text)
    history = max((score_message(m) for m in window), default=0)
    emotion = _EMOTION_OF.get(max(current, history), "calm")
    if history > current:
        uncertain.append("U1c 当前这句没有情绪词，但上文有")
    if _SARCASM.search(text):
        uncertain.append("U1d 可能是反讽或隐含不满")
    return RuleJudgment(intent=intent, emotion=emotion, uncertain=uncertain, complaint=complaint)


def _parse_model(text: str, customer: list[str]) -> tuple[str, str, str, list[str]]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("not an object")
    intent = str(data.get("intent", "")).strip().lower()
    emotion = str(data.get("emotion_level", data.get("emotionLevel", ""))).strip().lower()
    if intent not in INTENTS or emotion not in EMOTIONS:
        raise ValueError(f"off-contract labels intent={intent!r} emotion={emotion!r}")
    evidence = str(data.get("evidence") or "").strip()
    notes: list[str] = []
    if emotion != "calm" and (not evidence or not any(evidence in m for m in customer)):
        notes.append("U2 模型给的情绪依据不在消费者原话里")
        emotion = ""
        evidence = ""
    return intent, emotion, evidence, notes


def understand(latest: str, recent: list[str], *,
               ask_model: Callable[[str, dict], str] | None = None) -> Understanding:
    """``recent`` 为当前这句之前的消费者消息；``ask_model(system, payload) -> text`` 为空时只用规则。"""
    rule = rule_judgment(latest, recent)
    result = Understanding(intent=rule.intent, emotion_level=rule.emotion, rule_intent=rule.intent,
                           rule_emotion=rule.emotion)
    if not rule.uncertain:
        result.reasons.append("规则可直接判断，不调用模型")
    elif ask_model is None:
        result.reasons.extend([*rule.uncertain, "未配置模型，采用规则结论"])
    else:
        customer = [m for m in [*recent[-3:], latest] if m]
        payload = {"recentCustomerMessages": customer[:-1], "latestCustomerMessage": latest,
                   "ruleHints": {"intent": rule.intent, "emotionLevel": rule.emotion}}
        result.reasons.extend(rule.uncertain)
        try:
            intent, emotion, evidence, notes = _parse_model(ask_model(UNDERSTAND_SYSTEM, payload), customer)
            result.intent, result.source, result.evidence = intent, "model", evidence
            result.emotion_level = emotion or rule.emotion
            result.reasons.extend(notes)
        except Exception as exc:  # 模型失败不影响回复
            result.source = "rule_fallback"
            result.reasons.append(f"模型判断失败，采用规则结论：{type(exc).__name__}")
    if rule.complaint:  # U3 安全底线
        if _RANK[result.emotion_level] < _RANK["angry"]:
            result.emotion_level = "angry"
            result.reasons.append("U3 当前这句有投诉/曝光信号，情绪不低于 angry")
        if result.intent not in {"adverse_reaction", "complaint"} and not _rule_intents(latest):
            result.intent = "complaint"
    return result


def summary(result: Understanding) -> str:
    label = {"rule": "规则判定", "model": "模型判定", "rule_fallback": "模型失败，按规则"}[result.source]
    intent = INTENT_TEXT.get(result.intent, result.intent)
    emotion = EMOTION_TEXT.get(result.emotion_level, result.emotion_level)
    return f"{label}：意图 {intent}，情绪 {emotion}" + (
        f"（依据「{result.evidence}」）" if result.evidence else "")


def payload_for_composer(result: Any) -> dict | None:
    return result.prompt_dump() if isinstance(result, Understanding) else None
