"""分诊 A1 路由表 R1（规则版）。

失败方式：
T1 寒暄、纯物流/售后进度被派发知识（多花检索）。
T2 商品、成分、肤质、不良反应问题没有派发知识（漏资料）。
T3 带图没有派发视觉，或带图时跳过知识。
T4 判断不了时没有走保守路由。
T5 寒暄但上文在问商品时跳过知识。
T6 轨迹查询在任何路由下被跳过。
"""

import pytest

from app.domain.consumer_service.triage import triage


@pytest.mark.parametrize("text", ["在吗", "谢谢", "好的", "我的快递怎么还没到", "退款什么时候到账", "帮我改一下地址"])
def test_small_talk_and_progress_skip_knowledge(text):
    route = triage(text, [], has_images=False)
    assert route.knowledge is False and route.workers() == ["trajectory"]  # T1 / T6


@pytest.mark.parametrize("text", ["这款面霜敏感肌能用吗", "孕妇可以用这个精华吗", "用完脸上红肿刺痛", "快递到了，这个怎么用"])
def test_product_questions_dispatch_knowledge(text):
    route = triage(text, [], has_images=False)
    assert route.knowledge is True and route.trajectory is True  # T2 / T6


def test_images_dispatch_vision_and_knowledge():
    route = triage("", [], has_images=True)
    assert route.vision is True and route.knowledge is True  # T3


def test_unknown_message_is_conservative():
    route = triage("你们这服务也太差了吧", [], has_images=False)
    assert route.conservative is True and route.knowledge is True  # T4


def test_small_talk_after_product_question_keeps_knowledge():
    route = triage("好的", ["这个精华孕妇能用吗"], has_images=False)
    assert route.knowledge is True  # T5


def test_hints_are_recorded():
    route = triage("用完脸上红肿刺痛，太离谱了", [], has_images=False)
    dumped = route.dump()
    assert dumped["intent_hint"] == "adverse_reaction"
    assert dumped["workers"] == ["trajectory", "knowledge"] and dumped["reasons"]
