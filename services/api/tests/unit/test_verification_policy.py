"""按需语义核验（改进方案 P0-2 第 4 步）。

先列失败方式，再实现 `app.domain.consumer_service.verification_policy`：

跳过核验即放行，所以“漏判为无事实”是红线失败，误判为“需要核验”只多花一次调用。
已知失败方式与预期：
F1 回复带来源引用（claims/segments 引用了订单、工单、知识）却被判为无事实 -> 必须核验。
F2 回复正文含订单号/工单号/批次号/金额/日期/时长等数字，模型却没给引用 -> 必须核验。
F3 回复含状态词（已发货、已退款、已签收、到账、审核通过……）但无数字 -> 必须核验。
F4 回复含成分、功效、适用性断言（含/不含某成分、适合敏感肌、可以祛痘、孕妇可用） -> 必须核验。
F5 回复点名商品身份（“这款…霜/精华/面膜/水乳”等具体品名） -> 必须核验。
F6 存在个性化建议、服务断点或图片观察时，模型核验负责交叉检查 -> 必须核验。
F7 当前风险为高、或意图为不良反应/投诉 -> 必须核验（安全类问题宁严勿松）。
F8 只有寒暄、共情、补问（“亲，抱歉让您久等了”“方便拍一下成分表吗”）且无上述信号 -> 跳过。
F9 关闭开关（verify_on_demand=False）时一律核验，保留旧行为。
F10 返回原因列表，供审计 `verifySkippedReason`/`verifyReasons` 使用，不能只给布尔。
"""

from __future__ import annotations

import pytest

from app.domain.consumer_service.verification_policy import verification_reasons


def reply(body: str, refs: list[str] | None = None) -> dict:
    return {"body": body, "source_refs": refs or []}


def reasons(replies, **kwargs):
    defaults = {"has_advice": False, "has_breakpoints": False, "has_images": False,
                "risk_level": "none", "intent": "other", "enabled": True}
    defaults.update(kwargs)
    return verification_reasons(replies, **defaults)


def test_f1_cited_reply_requires_verification():
    assert "cited" in reasons([reply("亲，帮您看到了", ["order:6920223542160114724"])])


@pytest.mark.parametrize("body", [
    "订单6920223542160114724这边看到了哦",
    "退款8.8元会原路退回",
    "预计3个工作日内处理",
    "5月8日前会有结果",
    "工单S00059已在跟进",
    "批次26A18的我们登记一下",
])
def test_f2_numbers_require_verification(body):
    assert "number" in reasons([reply(body)])


@pytest.mark.parametrize("body", ["您的包裹已发货啦", "款项已退款成功", "显示已签收了", "钱还没到账是吗"])
def test_f3_status_words_require_verification(body):
    assert "status" in reasons([reply(body)])


@pytest.mark.parametrize("body", ["这款含有烟酰胺哦", "不含酒精的", "适合敏感肌使用", "可以祛痘淡印", "孕妇也能用"])
def test_f4_ingredient_and_efficacy_require_verification(body):
    assert "efficacy" in reasons([reply(body)])


@pytest.mark.parametrize("body", ["您说的积雪草修护霜我帮您看下", "这款面膜我帮您记下了", "小蜜罐水乳是套装哦"])
def test_f5_product_identity_requires_verification(body):
    assert "product" in reasons([reply(body)])


@pytest.mark.parametrize("flag,reason", [
    ("has_advice", "advice"), ("has_breakpoints", "breakpoints"), ("has_images", "images"),
])
def test_f6_cross_source_outputs_require_verification(flag, reason):
    assert reason in reasons([reply("亲，在的呢")], **{flag: True})


@pytest.mark.parametrize("kwargs", [{"risk_level": "high"}, {"intent": "adverse_reaction"}, {"intent": "complaint"}])
def test_f7_high_risk_or_safety_intent_requires_verification(kwargs):
    assert reasons([reply("亲，非常抱歉给您带来不好的体验")], **kwargs)


@pytest.mark.parametrize("body", [
    "亲，抱歉让您久等了，我在的呢",
    "方便拍一下外包装上的成分表吗？",
    "理解您的着急，您用完之后皮肤是什么感觉呢？",
])
def test_f8_pure_empathy_or_follow_up_question_skips(body):
    assert reasons([reply(body), reply("好的亲")]) == []


def test_f9_disabled_policy_always_verifies():
    assert reasons([reply("亲，在的呢")], enabled=False) == ["policy_disabled"]


def test_f10_any_reply_with_signal_triggers_whole_draft():
    assert reasons([reply("亲，在的呢"), reply("已发货了哦")]) == ["status"]
