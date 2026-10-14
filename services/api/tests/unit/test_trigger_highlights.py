"""风险依据触发词高亮（P1-6）。先列失败方式，再实现：
H1 偏移错位：body[start:end] 不等于命中词。
H2 否定或转述（“不想投诉”“客服说可以投诉”）也被高亮。
H3 类型错误：投诉类应为 complaint，激烈表达为 angry，不满为 dissatisfied。
H4 重叠命中重复输出（同一位置出现两段）。
H5 客服消息或模型生成的服务断点依据带高亮。
H6 规则风险的消息依据没有带上高亮。
"""

from datetime import datetime
from itertools import pairwise

from app.domain.consumer_service.emotion import trigger_highlights
from app.domain.consumer_service.risk_rules import RuleMessage


def spans(text):
    return [(text[h.start:h.end], h.kind) for h in trigger_highlights(text)]


def test_h1_h3_offsets_and_kinds():
    text = "再不处理我就去12315投诉，骗子！"
    assert spans(text) == [("12315", "complaint"), ("投诉", "complaint"), ("骗子", "angry")]
    assert spans("这也太过分了") == [("过分", "dissatisfied")]


def test_h2_negated_or_reported_not_highlighted():
    assert spans("我不想投诉，只想尽快解决") == []
    assert spans("客服说可以投诉吗") == []


def test_h4_no_overlaps():
    result = trigger_highlights("怎么还没到")
    ordered = sorted((h.start, h.end) for h in result)
    assert all(a[1] <= b[0] for a, b in pairwise(ordered))


def test_h5_h6_rule_evidence():
    at = datetime(2026, 5, 7, 10)
    customer = RuleMessage(ref="m1", conversation_id="S1", buyer="b", body="空包裹，我要投诉", at=at)
    support = RuleMessage(ref="m2", conversation_id="S1", buyer="b", body="您可以投诉", at=at, sender_role="support")
    evidence = customer.evidence()
    assert [(evidence.body[h.start:h.end], h.kind) for h in evidence.highlights] == [("投诉", "complaint")]
    assert support.evidence().highlights == []
