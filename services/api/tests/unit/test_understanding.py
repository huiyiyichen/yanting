"""意图与情绪 Agent（从起草拆出）。

失败方式：
U1 规则能判断时仍调用模型（浪费 Token）；拿不准（无意图、混合意图、情绪只在上文、反讽）时不问模型。
U2 模型编造情绪依据（不在原话里）仍被采信。
U3 当前这句明确要投诉，模型判成平稳后被采信，漏掉风险。
U4 模型失败、输出越界时链路中断，而不是退回规则。
"""

import json

import pytest

from app.domain.consumer_service.understanding import rule_judgment, understand


def _model(reply: dict | str):
    calls = []

    def ask(system, payload):
        calls.append(payload)
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
    return ask, calls


@pytest.mark.parametrize("text,intent,emotion", [
    ("我的快递到哪了", "logistics", "calm"),
    ("这款精华敏感肌能用吗", "product_question", "calm"),
    ("用了之后脸上红肿刺痛", "adverse_reaction", "dissatisfied"),
    ("谢谢", "other", "calm"),
    ("退款什么时候到账", "refund", "calm"),
])
def test_rule_confident_cases_skip_model(text, intent, emotion):
    ask, calls = _model({"intent": "other", "emotion_level": "calm", "evidence": ""})
    found = understand(text, [], ask_model=ask)
    assert (found.intent, found.emotion_level, found.source) == (intent, emotion, "rule")
    assert calls == []  # U1


@pytest.mark.parametrize("text,recent,reason", [
    ("我上周买的那个东西呢", [], "U1a"),
    ("这款面霜适合干皮吗，顺便问下什么时候发货", [], "U1b"),
    ("好吧那我再等等", ["怎么还没发货，太过分了"], "U1c"),
    ("呵呵，你们服务真好啊", [], "U1d"),
])
def test_uncertain_cases_ask_model(text, recent, reason):
    assert any(r.startswith(reason) for r in rule_judgment(text, recent).uncertain)
    ask, calls = _model({"intent": "logistics", "emotion_level": "dissatisfied", "evidence": text[:4]})
    found = understand(text, recent, ask_model=ask)
    assert len(calls) == 1 and found.source == "model"  # U1
    assert calls[0]["latestCustomerMessage"] == text


def test_sarcasm_model_reads_implicit_dissatisfaction():
    ask, _ = _model({"intent": "other", "emotion_level": "dissatisfied", "evidence": "服务真好啊"})
    found = understand("呵呵，你们服务真好啊", [], ask_model=ask)
    assert found.rule_emotion == "calm" and found.emotion_level == "dissatisfied"
    assert found.evidence == "服务真好啊"


def test_invented_evidence_falls_back_to_rule_emotion():
    ask, _ = _model({"intent": "logistics", "emotion_level": "angry", "evidence": "我要投诉你们"})
    found = understand("我上周买的那个东西呢", [], ask_model=ask)
    assert found.intent == "logistics" and found.emotion_level == "calm"  # U2
    assert any(r.startswith("U2") for r in found.reasons)


def test_complaint_signal_is_never_downgraded():
    ask, _ = _model({"intent": "other", "emotion_level": "calm", "evidence": ""})
    found = understand("再不处理我就打12315，呵呵", [], ask_model=ask)
    assert found.emotion_level == "angry" and found.intent == "complaint"  # U3


@pytest.mark.parametrize("reply", ["不是JSON", {"intent": "chitchat", "emotion_level": "calm"}, {"x": 1}])
def test_bad_model_output_falls_back(reply):
    ask, _ = _model(reply)
    found = understand("我上周买的那个东西呢", [], ask_model=ask)
    assert found.source == "rule_fallback" and found.intent == "other"  # U4


def test_model_exception_falls_back():
    def boom(system, payload):
        raise TimeoutError
    found = understand("呵呵，你们服务真好啊", [], ask_model=boom)
    assert found.source == "rule_fallback" and found.emotion_level == "calm"
