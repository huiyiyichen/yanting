"""风险队列迷你声纹序列 emotion_sequence。

失败方式：
F1 客服连续多条回复各占一格，把消费者情绪挤出窗口；
F2 只保留最早的若干轮，看不到最近的情绪；
F3 空消息/系统消息也占格；
F4 消费者情绪档位与 score_message 不一致。
"""

from app.domain.consumer_service.emotion import emotion_sequence, score_message


def test_service_replies_merge_and_customer_levels_follow_rules():
    rows = [("customer", "你好"), ("operator", "在的"), ("assistant", "稍等"),
            ("customer", "怎么还没发货"), ("system", "转人工"), ("customer", "  ")]
    assert emotion_sequence(rows) == ["c0", "o", f"c{score_message('怎么还没发货')}"]


def test_keeps_latest_window():
    rows = [("customer", f"第{i}次") for i in range(20)] + [("customer", "再不处理我就投诉到12315")]
    seq = emotion_sequence(rows, limit=12)
    assert len(seq) == 12 and seq[-1] == "c2"
