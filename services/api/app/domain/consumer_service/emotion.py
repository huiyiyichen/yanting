"""消费者消息情绪规则：逐条打分并判断情绪升级。

PRD 4.3：连续消息情绪从平稳或不满升级为愤怒时预警。这里只用固定词表，
不调用模型，导入数据和客户新消息都能立即判断；模型结果只作为补充来源。

分值：0 平稳、1 不满、2 愤怒。愤怒词表限定为投诉/威胁类表达，
“退款”“退钱”是普通诉求，不计分。词前紧邻“不/没/别”视为否定（如“就不投诉了”）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.domain.enums import EmotionLevel, EmotionTrend

CALM, DISSATISFIED, ANGRY = 0, 1, 2

#: 向第三方投诉或公开的表达，同时用于“投诉风险”
COMPLAINT_TERMS = ("投诉", "12315", "举报", "曝光", "差评")

_ANGRY_TERMS = (
    *COMPLAINT_TERMS,
    "等着瞧",
    "你们等着",
    "骗子",
    "骗人",
    "必须给我个说法",
    "别想赖",
    "钱要定了",
    "不能不认",
    "忍无可忍",
    "不可理喻",
    "根本没在听",
    "不把客户当回事",
)

_DISSATISFIED_TERMS = (
    "什么玩意",
    "啥玩意",
    "开什么玩笑",
    "开啥玩笑",
    "搞啥",
    "坑",
    "过分",
    "无语",
    "服了",
    "假货",
    "破规则",
    "不信我",
    "靠谱点",
    "别拖",
    "别让我",
    "别再",
    "快点",
    "到底",
    "咋还",
    "怎么还",
    "还没",
    "没收到",
    "少了",
    "少发",
    "漏发",
    "坏的",
    "碎了",
    "破损",
    "不对",
    "失望",
    "着急",
    "急死",
    "不舒服",
    "痒",
    "发红",
    "红肿",
    "刺痛",
    "痘",
    "过敏",
    "赔偿",
    "医药费",
    "说法",
    "赶紧",
    "麻利",
    "不满",
)


def _pattern(terms: Iterable[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<![不没别])(?:{alternatives})")


_ANGRY_RE = _pattern(_ANGRY_TERMS)
_DISSATISFIED_RE = _pattern(_DISSATISFIED_TERMS)
_COMPLAINT_RE = _pattern(COMPLAINT_TERMS)

_LEVELS = {
    CALM: EmotionLevel.CALM,
    DISSATISFIED: EmotionLevel.DISSATISFIED,
    ANGRY: EmotionLevel.ANGRY,
}


def score_message(text: str) -> int:
    if _has_signal(_ANGRY_RE, text):
        return ANGRY
    if _has_signal(_DISSATISFIED_RE, text):
        return DISSATISFIED
    return CALM


def level_of(score: int) -> EmotionLevel:
    return _LEVELS[score]


def has_complaint_signal(text: str) -> bool:
    return _has_signal(_COMPLAINT_RE, text)


def _has_signal(pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text):
        prefix = re.split(r"[，。；！？,;!?\n]", text[:match.start()])[-1][-40:]
        sentence_prefix = re.split(r"[。；！？;!?\n]", text[:match.start()])[-1][-80:]
        suffix = re.split(r"[，。；！？,;!?\n]", text[match.end():])[0]
        if re.search(r"(不想|不会|不再|不用|不需要|没有|不是来|不是要|并非要|不要|不打算|不准备)(再|去|进行)?$", prefix):
            continue
        # A process question or someone else's advice is not the customer's current threat.
        explicit = bool(re.search(r"(我|本人).{0,6}(要|会|决定|现在|正式|已经|准备).{0,6}$", prefix))
        if not explicit and (
            re.search(r"(客服|你们|平台|朋友|他|她).{0,5}(说|提到|建议|告诉).*$", prefix)
            or (re.search(r"如果(我|以后|将来|未来)", sentence_prefix) and re.search(r"吗|么|如何|怎么|流程|途径", suffix))
        ):
            continue
        return True
    return False


@dataclass(frozen=True)
class CustomerMessage:
    """参与情绪判断的一条消费者消息。`ref` 是可回溯的源记录或消息 ID。"""

    ref: str
    body: str


@dataclass(frozen=True)
class Escalation:
    from_score: int
    baseline: CustomerMessage
    trigger: CustomerMessage


def detect_escalation(messages: Sequence[CustomerMessage]) -> Escalation | None:
    """先出现平稳或不满的消息、之后出现愤怒消息，即为情绪升级。

    返回第一次升级的起点和触发消息；一开始就愤怒、之后平复的会话不算升级。
    """

    baseline: tuple[int, CustomerMessage] | None = None
    for message in messages:
        if not message.body.strip():
            continue
        score = score_message(message.body)
        if score < ANGRY:
            if baseline is None or score > baseline[0]:
                baseline = (score, message)
        elif baseline is not None:
            return Escalation(from_score=baseline[0], baseline=baseline[1], trigger=message)
    return None


def emotion_trend(bodies: Iterable[str]) -> EmotionTrend:
    scores = [score_message(body) for body in bodies if body.strip()]
    if len(scores) < 2:
        return EmotionTrend.UNKNOWN
    if scores[-1] > scores[-2]:
        return EmotionTrend.RISING
    if scores[-1] < scores[-2]:
        return EmotionTrend.FALLING
    if len(set(scores)) > 1:
        return EmotionTrend.REPEATED
    return EmotionTrend.STABLE
