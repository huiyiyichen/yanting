"""情绪打分与情绪升级规则。样例取自官方聊天记录的买家原话。"""

from __future__ import annotations

import pytest

from app.domain.consumer_service.emotion import (
    ANGRY,
    CALM,
    DISSATISFIED,
    CustomerMessage,
    detect_escalation,
    has_complaint_signal,
    score_message,
)


def _messages(*bodies: str) -> list[CustomerMessage]:
    return [CustomerMessage(f"m{index}", body) for index, body in enumerate(bodies)]


S00059 = _messages(
    "你们发的什么玩意儿，箱子打开里面是空的！我要仅退款，不退货啊，货都没退什么退",
    "拍什么拍，我说空的就是空的，你是不信我？赶紧退款",
    "搞这么复杂，那算了，我平台申请仅退款，你们等着！",
    "哼，等着瞧",
)
S00015 = _messages(
    "必须给我个说法！用了你们面膜脸过敏，红肿刺痛，我人现在在医院！",
    "资料给你，咋赔偿说个方案，不行我就走12315",
    "那个，能，动作快点点，别让我再跑一趟医院",
    "支付宝就是我手机号，医生开了氯雷他定和一支药膏哦",
    "好，等钱到账就行！",
)
S00016 = _messages(
    "你好，订单6920470451725491723的退款咋还没到账啊，都两天了",
    "刚看到银行短信了，到了到了，谢谢哈，麻烦了",
)


def test_rising_to_angry_is_escalation() -> None:
    escalation = detect_escalation(S00059)
    assert escalation is not None
    assert escalation.from_score == DISSATISFIED
    assert escalation.baseline.ref == "m0"
    assert escalation.trigger.ref == "m2"


def test_angry_from_start_then_calming_is_not_escalation() -> None:
    assert score_message(S00015[0].body) == ANGRY
    assert detect_escalation(S00015) is None


def test_calm_refund_question_is_not_escalation() -> None:
    assert score_message(S00016[1].body) == CALM
    assert detect_escalation(S00016) is None


def test_calm_to_angry_is_escalation() -> None:
    escalation = detect_escalation(_messages("帮我看下订单到哪了", "再不给说法我就去投诉"))
    assert escalation is not None
    assert escalation.from_score == CALM


@pytest.mark.parametrize(
    "body",
    ["你好，订单的退款咋还没到账啊", "那我退，钱赶紧退给我", "想退货，还没拆封"],
)
def test_refund_request_alone_is_not_angry(body: str) -> None:
    assert score_message(body) < ANGRY


def test_negated_complaint_is_not_angry() -> None:
    body = "行，看在处理挺快的份上就不投诉了，下不为例啊"
    assert score_message(body) < ANGRY
    assert not has_complaint_signal(body)


def test_complaint_signal() -> None:
    assert has_complaint_signal("最好快点解决，不然我直接投诉到平台")
    assert has_complaint_signal("不行我就走12315")
    assert not has_complaint_signal("好的，麻烦啦")


def test_blank_messages_are_skipped() -> None:
    assert detect_escalation(_messages("", "   ", "投诉")) is None
