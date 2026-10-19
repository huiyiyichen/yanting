"""分诊 Agent A1（多 Agent 阶段 2 简化版）：规则优先决定本轮派哪些取证 Worker。

只在 orchestration=multi 时运行。判断依据只有当前消息、最近几条消费者消息和是否带图，
不读数据库，所以可以放在取证之前、几乎不增加时延。

路由表 R1：
- 轨迹查询（trajectory）：总是派发。订单、工单和历史消息是核验的事实来源，跳过它会让核验失去依据。
- 视觉（vision）：本轮有图片就派发。
- 知识（knowledge）：命中商品/成分/功效/用法/肤质/不良反应等词，或判断不了时派发（保守路由）；
  只有寒暄、致谢，或纯物流/订单/退款进度且不涉及商品时才跳过。

分诊出错或输入异常时返回保守路由（全部派发），回复链路照常进行。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.domain.consumer_service.emotion import (
    ANGRY,
    DISSATISFIED,
    has_complaint_signal,
    score_message,
)

TRIAGE_VERSION = "YT_TRIAGE_RULES@1"

_PRODUCT = re.compile(
    r"成分|功效|效果|用法|怎么用|如何用|用量|顺序|搭配|适合|适用|肤质|敏感肌|油皮|干皮|混油|痘|闭口|美白|抗老|"
    r"保湿|防晒|色号|质地|味道|香味|孕妇|哺乳|保质期|有效期|开封|真假|正品|批次|区别|推荐|哪款|什么商品|这是什么|"
    r"面霜|精华|乳液|水乳|洁面|卸妆|眼霜|面膜|口红|粉底|安瓶|玻尿酸|视黄醇|烟酰胺|A醇|"
    r"过敏|红肿|刺痛|发痒|瘙痒|起疹|泛红|不适|烂脸|就医"
)
# “不适合 / 不适用”是选购问题，不是皮肤不适
_ADVERSE = re.compile(r"过敏|红肿|刺痛|发痒|瘙痒|起疹|泛红|不适(?![合用])|烂脸|就医|医院|呼吸困难")
_LOGISTICS = re.compile(
    r"物流|快递|发货|到哪|到了没|没到|还没到|几天到|单号|签收|派送|揽收|催|退款|退货|换货|补发|进度|到账|打款|"
    r"订单|取消|地址|改地址|拦截"
)
_SMALL_TALK = re.compile(r"^(在吗|在不在|你好|您好|hi|hello|哈喽|谢谢|多谢|感谢|好的|好|嗯|嗯嗯|ok|收到|知道了|行)[!！。.~～?？\s]*$",
                         re.IGNORECASE)

_INTENT_RULES = (
    ("adverse_reaction", _ADVERSE),
    ("refund", re.compile(r"退款|打款|到账")),
    ("return", re.compile(r"退货")),
    ("replacement", re.compile(r"换货|补发|少发|漏发|发错")),
    ("logistics", re.compile(r"物流|快递|发货|到哪|没到|几天到|单号|签收|派送|揽收")),
    ("order_status", re.compile(r"订单|取消|改地址")),
    ("product_question", _PRODUCT),
)
_EMOTION = {ANGRY: "angry", DISSATISFIED: "dissatisfied"}


@dataclass
class TriageRoute:
    trajectory: bool = True
    knowledge: bool = True
    vision: bool = False
    intent_hint: str = "unknown"
    emotion_hint: str = "calm"
    complaint: bool = False
    conservative: bool = False
    reasons: list[str] = field(default_factory=list)
    version: str = TRIAGE_VERSION

    def workers(self) -> list[str]:
        return [name for name in ("trajectory", "knowledge", "vision") if getattr(self, name)]

    def dump(self) -> dict:
        return {**asdict(self), "workers": self.workers()}


def conservative_route(has_images: bool, reason: str) -> TriageRoute:
    return TriageRoute(knowledge=True, vision=has_images, conservative=True, reasons=[reason])


def triage(latest_message: str, recent_customer: list[str], *, has_images: bool) -> TriageRoute:
    """规则分诊。``recent_customer`` 为最近几条消费者消息（不含当前这条也可以）。"""
    try:
        return _triage(latest_message or "", [m for m in recent_customer if m], has_images=has_images)
    except Exception as exc:  # pragma: no cover - 防御：分诊故障一律保守路由
        return conservative_route(has_images, f"分诊异常，按保守路由全部派发：{type(exc).__name__}")


def _triage(latest: str, recent: list[str], *, has_images: bool) -> TriageRoute:
    text = latest.strip()
    window = " ".join([*recent[-2:], text])
    route = TriageRoute(vision=has_images)

    route.intent_hint = next((intent for intent, pattern in _INTENT_RULES if pattern.search(text)), "unknown")
    if route.intent_hint == "unknown" and _SMALL_TALK.match(text):
        route.intent_hint = "other"
    level = max((score_message(m) for m in [*recent[-2:], text]), default=0)
    route.emotion_hint = _EMOTION.get(level, "calm")
    route.complaint = has_complaint_signal(window)

    if has_images:
        route.reasons.append("带图：派发视觉；图中商品需要知识资料对照")
        route.knowledge = True
    elif _PRODUCT.search(text):
        route.reasons.append("涉及商品/成分/用法/肤质或不良反应：派发知识")
        route.knowledge = True
    elif _SMALL_TALK.match(text):
        # 寒暄但上文在问商品时，仍然查知识，避免“好的，那敏感肌能用吗”被拆成两轮后丢资料
        route.knowledge = bool(_PRODUCT.search(" ".join(recent[-2:])))
        route.reasons.append("寒暄/致谢" + ("，上文涉及商品：派发知识" if route.knowledge else "：跳过知识"))
    elif _LOGISTICS.search(text):
        route.knowledge = False
        route.reasons.append("物流/订单/售后进度，不涉及商品：跳过知识，事实来自轨迹查询")
    else:
        route.knowledge = True
        route.conservative = True
        route.reasons.append("规则判断不了：保守路由，派发知识")
    route.reasons.append("轨迹查询总是派发：订单、工单和历史消息是核验依据")
    return route
