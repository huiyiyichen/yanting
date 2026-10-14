"""客服发送前质检（改进方案 P1-5），纯规则，不调模型。

先列失败方式，再实现 `app.domain.consumer_service.draft_review.review_draft`：
R1 无依据承诺（保证、一定到账、马上退、肯定没问题）未提示。
R2 医学结论（就是过敏、没事的可以继续用、不用就医）未提示，且严重度不是 high。
R3 草稿中的金额与来源目录（订单实付、工单退款金额）不一致未提示；一致时误报。
R4 草稿中的订单号/工单号不在来源目录中未提示；在目录中误报。
R5 当前情绪为激烈时出现“按流程/请理解/系统规定”未提示；情绪平稳时误报。
R6 正常回复（共情 + 补问）被误报，阻断正常发送。
R7 否定与劝阻语境被误报：“建议您先停用并及时就医”不是医学结论；“不能保证”不是承诺。
R8 每条提示必须带类别、严重度和命中原文片段，供前端标注与审计。
"""

from __future__ import annotations

import pytest

from app.domain.consumer_service.draft_review import review_draft

CATALOG = {"amounts": {"8.80", "129.00"}, "ids": {"6920223542160114724", "W2026050701"}}


def kinds(text: str, emotion: str = "calm") -> set[str]:
    return {item.kind for item in review_draft(text, catalog=CATALOG, emotion=emotion)}


@pytest.mark.parametrize("text", ["保证今天给您退回来", "一定到账的您放心", "马上退给您", "肯定没问题的"])
def test_r1_unfounded_promise(text):
    assert "unfounded_promise" in kinds(text)


@pytest.mark.parametrize("text", ["这就是过敏，没事的", "没事的可以继续用", "不用就医，过两天就好"])
def test_r2_medical_conclusion_is_high(text):
    findings = [f for f in review_draft(text, catalog=CATALOG, emotion="calm") if f.kind == "medical"]
    assert findings and findings[0].severity == "high"


def test_r3_amount_mismatch_and_match():
    assert "fact_mismatch" in kinds("给您退款9.80元")
    assert "fact_mismatch" not in kinds("给您退款8.80元")
    assert "fact_mismatch" not in kinds("退款¥129已原路退回")


def test_r4_unknown_identifier():
    assert "fact_mismatch" in kinds("订单6920223542160119999已处理")
    assert "fact_mismatch" not in kinds("订单6920223542160114724已处理")


def test_r5_cold_template_only_when_angry():
    assert "cold_tone" in kinds("按流程需要先核实", emotion="angry")
    assert "cold_tone" not in kinds("按流程需要先核实", emotion="calm")


@pytest.mark.parametrize("text", ["亲，非常抱歉让您久等了，方便发一下外包装照片吗？", "理解您的着急，我这边马上帮您核实"])
def test_r6_normal_reply_has_no_findings(text):
    assert kinds(text, emotion="angry") == set()


@pytest.mark.parametrize("text", ["建议您先停用，并及时就医", "这边不能保证具体到账时间"])
def test_r7_negated_or_advisory_context(text):
    assert kinds(text) == set()


def test_r8_findings_carry_kind_severity_and_quote():
    finding = review_draft("保证明天到", catalog=CATALOG, emotion="calm")[0]
    assert finding.kind and finding.severity in {"high", "medium"} and finding.quote == "保证"
    assert finding.start == 0 and finding.end == 2
