"""消费者画像卡与承诺追踪（改进方案 P1-2）。

先列失败方式，再实现 `app.domain.consumer_service.consumer_profile`：

承诺期限（纯函数）
P1 “N 个工作日”未识别，承诺被漏掉。
P2 工作日跨周末计数错误：应从发言次日起跳过周六、周日，到第 N 个工作日 23:59:59（UTC+8）。
P3 周五/周六发言的第 1 个工作日应是下周一。
P4 无明确期限（“尽快”“第一时间”）却生成到期日。
P5 消费者发言被当作承诺；只取客服或 AI 的实际发言。
P6 一句话含两个期限（无法判定哪一个）时仍生成到期日。
承诺状态
P7 没有业务记录证据却标 fulfilled。
P8 截止前标 due，或截止后仍标 pending。
P9 同买家在承诺后完成的线下打款工单是兑现证据 -> fulfilled，并引用工单。
画像聚合
P10 进线次数把查看时点之后的会话也算进来（时间因果）。
P11 无显式客户 ID 时按昵称聚合，却没有标明 aggregation=buyer_alias。
P12 肤质在消费者未自述时出现，或来自客服/AI 发言；更正后仍显示旧肤质。
P13 “已拒绝”来自客服发言，或缺少原话来源。
P14 页面读取画像触发模型调用。
剧情 A：S00059 显示 05/05 承诺“3 个工作日未到账则线下补款”，到期 05/08，状态 pending。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.consumer_service.consumer_profile import (
    PromiseStatement,
    extract_promise,
    promise_status,
    self_reported_skin,
    workday_deadline,
)

CST = timezone(timedelta(hours=8))


def cst(*args) -> datetime:
    return datetime(*args, tzinfo=CST)


@pytest.mark.parametrize("made,days,due", [
    (cst(2026, 5, 5, 12, 8), 3, cst(2026, 5, 8, 23, 59, 59)),     # 周二 -> 周五
    (cst(2026, 5, 7, 9, 0), 3, cst(2026, 5, 12, 23, 59, 59)),     # 周四 -> 跨周末到周二
    (cst(2026, 5, 8, 22, 0), 1, cst(2026, 5, 11, 23, 59, 59)),    # 周五 -> 下周一
    (cst(2026, 5, 9, 10, 0), 1, cst(2026, 5, 11, 23, 59, 59)),    # 周六 -> 下周一
])
def test_p2_p3_workday_deadline_skips_weekends(made, days, due):
    assert workday_deadline(made, days) == due.astimezone(UTC)


def statement(text, role="operator", at=None):
    return PromiseStatement(source_ref="message:S1:m1", role=role, text=text,
                            at=at or cst(2026, 5, 5, 12, 8).astimezone(UTC))


def test_p1_workday_promise_is_extracted():
    promise = extract_promise(statement("若3个工作日内仍未到账，我们走线下打款直接补给您"))
    assert promise is not None
    assert promise.due_at == cst(2026, 5, 8, 23, 59, 59).astimezone(UTC)


def test_promise_card_keeps_only_the_deadline_clause():
    """全景方案 4.7：承诺卡只显示含期限的分句，期限单独给出供加粗，整句供悬停。"""
    text = "给您添麻烦了~提供下支付宝账号哈。若3个工作日内仍未到账，我们走线下打款直接补给您"
    promise = extract_promise(statement(text))
    assert promise.text == "若3个工作日内仍未到账，我们走线下打款直接补给您"
    assert promise.deadline == "3个工作日" and promise.full_text == text


@pytest.mark.parametrize("text", ["48小时内给您回复", "预计2天内联系您", "我们会在2026年5月9日前处理好"])
def test_p1_hour_day_and_date_promises_are_extracted(text):
    assert extract_promise(statement(text)) is not None


@pytest.mark.parametrize("text", ["有结果第一时间联系您", "尽快帮您处理", "这边已提交核实工单"])
def test_p4_vague_wording_has_no_deadline(text):
    assert extract_promise(statement(text)) is None


def test_p5_customer_words_are_not_promises():
    assert extract_promise(statement("3个工作日内不到账我就投诉", role="customer")) is None


def test_p6_two_deadlines_are_ambiguous():
    assert extract_promise(statement("24小时内回复，3个工作日内到账")) is None


def test_p7_p8_status_without_evidence():
    due = cst(2026, 5, 8, 23, 59, 59).astimezone(UTC)
    assert promise_status(due, as_of=cst(2026, 5, 7, 17, 41).astimezone(UTC), evidence=None) == "pending"
    assert promise_status(due, as_of=cst(2026, 5, 9, 0, 1).astimezone(UTC), evidence=None) == "due"


def test_p9_business_evidence_marks_fulfilled():
    due = cst(2026, 5, 8, 23, 59, 59).astimezone(UTC)
    assert promise_status(due, as_of=cst(2026, 5, 9).astimezone(UTC),
                          evidence="work_order:W1") == "fulfilled"


def test_p12_skin_type_only_from_customer_and_latest_correction_wins():
    messages = [
        ("customer", "message:c:1", "我是混干皮，两颊会起皮"),
        ("operator", "message:c:2", "油皮的话建议清爽型"),
        ("customer", "message:c:3", "更正一下，我其实更接近混合皮"),
    ]
    skin = self_reported_skin(messages)
    assert skin is not None and skin["text"] == "混合皮" and skin["sourceRef"] == "message:c:3"
    assert self_reported_skin([("operator", "message:c:2", "油皮的话建议清爽型")]) is None
