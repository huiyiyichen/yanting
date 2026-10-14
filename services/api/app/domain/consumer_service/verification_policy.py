"""按需语义核验：判断一份回复草稿是否必须交给模型做独立事实核验。

跳过核验等于放行，所以判定只做“宁严勿松”的信号检测：任何硬事实、
安全或跨来源信号都会触发核验；只有寒暄、共情与补问才跳过。
程序校验（来源目录、金额、编号、引用一致性）不受本函数影响，始终执行。
纯函数，不读数据库、不调模型。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

_NUMBER = re.compile(r"\d|[一二三四五六七八九十两]+\s*(?:个)?(?:工作日|天|小时|元|块|件|片|支|瓶|盒)")
_STATUS = re.compile(
    r"已?(?:发货|签收|揽收|派送|退款|退货|退回|到账|打款|补发|换货|审核|通过|驳回|关闭|完成|受理|登记|处理中|拦截)"
)
_EFFICACY = re.compile(
    r"含有?|不含|成分|配方|功效|祛|美白|淡斑|淡印|修护|保湿|控油|抗老|抗皱|防晒|敏感肌|孕妇|孕期|哺乳|"
    r"适合|适用|可以用|能用|不能用|致敏|过敏|刺激|安全"
)
_PRODUCT = re.compile(
    r"(?:这款|该款|那款)|[\u4e00-\u9fff]{1,10}(?:霜|乳|精华|面膜|水乳|水|露|油|膏|啫喱|气垫|粉底|唇|眼霜|洁面|套装|礼盒)"
)
# 补问外包装成分表属于沟通动作，不是成分断言；先剔除再检测。
_FOLLOW_UP = re.compile(r"(?:拍|看|提供|发)[^，。？！]{0,8}(?:成分表|外包装|商品照片|正面)")
_SAFETY_INTENTS = {"adverse_reaction", "complaint"}


def _text(reply: Mapping | object) -> tuple[str, list[str]]:
    if isinstance(reply, Mapping):
        return str(reply.get("body", "")), list(reply.get("source_refs", []))
    body = getattr(reply, "body", "")
    refs = [ref for claim in getattr(reply, "claims", []) for ref in claim.source_refs]
    refs += [ref for part in getattr(reply, "segments", []) for ref in part.source_refs]
    return body, refs


def verification_reasons(
    replies: Iterable[Mapping | object], *, has_advice: bool, has_breakpoints: bool,
    has_images: bool, risk_level: str, intent: str, enabled: bool = True,
) -> list[str]:
    """返回需要模型核验的原因；空列表表示只做程序校验即可。"""

    if not enabled:
        return ["policy_disabled"]
    reasons: list[str] = []

    def add(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    for reply in replies:
        body, refs = _text(reply)
        if refs:
            add("cited")
        scan = _FOLLOW_UP.sub("", body)
        if _NUMBER.search(scan):
            add("number")
        if _STATUS.search(scan):
            add("status")
        if _EFFICACY.search(scan):
            add("efficacy")
        if _PRODUCT.search(scan):
            add("product")
    if has_advice:
        add("advice")
    if has_breakpoints:
        add("breakpoints")
    if has_images:
        add("images")
    if risk_level == "high":
        add("high_risk")
    if intent in _SAFETY_INTENTS:
        add("safety_intent")
    return reasons
