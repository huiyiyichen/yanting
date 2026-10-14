"""改写结果保真校验（P1-3）。先列失败方式，再实现 `rewrite.rewrite_issues`：
W1 改写删掉了原文里的金额/订单号/日期等硬事实（应拒绝，保留原文）。
W2 改写新增了原文没有的数字、编号或金额（应拒绝）。
W3 改写新增了原文没有的成分功效、状态或商品身份断言（应拒绝）。
W4 改写引入无依据承诺或医学判断（应拒绝）。
W5 改写为空、过长（>800 字）或与原文完全相同（应拒绝，提示无变化）。
W6 只调整语气和语序、保留全部硬事实（应放行）。
"""

import pytest

from app.domain.consumer_service.rewrite import rewrite_issues

ORIGINAL = "亲，订单6920223542160114724的退款8.8元已提交核实，麻烦您再等等哦。"


@pytest.mark.parametrize("text", ["亲，退款已提交核实，麻烦您再等等哦。", "亲，订单的退款已提交核实。"])
def test_w1_dropping_facts_is_rejected(text):
    assert rewrite_issues(ORIGINAL, text)


@pytest.mark.parametrize("text", [
    "亲，订单6920223542160114724的退款8.8元已提交核实，3天内到账。",
    "亲，订单6920223542160114724的退款8.8元已提交核实，另补偿5元。",
])
def test_w2_new_numbers_rejected(text):
    assert rewrite_issues(ORIGINAL, text)


def test_w3_new_efficacy_or_status_rejected():
    assert rewrite_issues(ORIGINAL, "亲，订单6920223542160114724的退款8.8元已提交核实，这款面膜适合敏感肌。")
    assert rewrite_issues(ORIGINAL, "亲，订单6920223542160114724的退款8.8元已经到账了。")


@pytest.mark.parametrize("text", [
    "亲，订单6920223542160114724的退款8.8元保证马上退回。",
    "亲，订单6920223542160114724的退款8.8元已提交核实，过敏没事的可以继续用。",
])
def test_w4_promise_or_medical_rejected(text):
    assert rewrite_issues(ORIGINAL, text)


@pytest.mark.parametrize("text", ["", ORIGINAL, "亲" * 801])
def test_w5_empty_unchanged_or_too_long(text):
    assert rewrite_issues(ORIGINAL, text)


def test_w6_tone_only_change_passes():
    assert rewrite_issues(ORIGINAL, "亲亲别着急，订单6920223542160114724的退款8.8元已经提交核实啦，辛苦您再稍等一下～") == []
