from datetime import datetime, timedelta

import pytest

from app.domain.consumer_service.risk_rules import RuleMessage, RuleTicket, compute_signals
from app.domain.enums import ServiceRiskType as Kind

START = datetime(2026, 5, 1, 0, 0)


def msg(cid="c1", body="查询进度", hours=0, ref=None, shop="demo"):
    return RuleMessage(ref or f"{cid}-{hours}", cid, "buyer", body,
                       START + timedelta(hours=hours), shop=shop)


def ticket(key="t1", kind="offline_payment", order="order1", hours=0, **kwargs):
    return RuleTicket(key, key, "c1", "buyer", kind, order, "in_progress",
                      START + timedelta(hours=hours), **kwargs)


def kinds(messages=(), tickets=(), now=None, source_clock=None):
    return compute_signals(list(messages), list(tickets), now=now or START + timedelta(days=100),
                           source_clock=source_clock)


@pytest.mark.parametrize("hours, expected", [(71, True), (72, True), (73, False)])
def test_repeated_contact_has_an_inclusive_72_hour_window(hours, expected):
    signals = kinds([msg(), msg("c2", hours=hours)])
    assert any(s.kind == Kind.REPEATED_CONTACT for s in signals) is expected


def test_same_alias_in_different_shops_is_not_joined():
    assert not any(s.kind == Kind.REPEATED_CONTACT for s in kinds(
        [msg(shop="shop-a"), msg("c2", hours=1, shop="shop-b")]))


@pytest.mark.parametrize("types, expected", [
    (["退款", "退款"], True), (["价格补差", "退款"], False),
    (["补偿", "价格补差"], False), (["退款补差", "退款"], False),
])
def test_refund_is_not_every_offline_payment(types, expected):
    signals = kinds(tickets=[ticket(f"t{i}", detail={"paymentType": value})
                             for i, value in enumerate(types)])
    assert any(s.kind == Kind.REPEATED_REFUND for s in signals) is expected


def test_missing_order_is_not_a_shared_refund_bucket():
    assert not kinds(tickets=[ticket("t1", order=None, detail={"paymentType": "退款"}),
                              ticket("t2", order=None, detail={"paymentType": "退款"})])


def test_same_refund_id_is_one_return_request():
    assert not kinds(tickets=[
        ticket("t1", kind="return_refund", detail={"refundId": "r1"}),
        ticket("t2", kind="return_refund", detail={"refundId": "r1"}),
    ])
    signals = kinds(tickets=[
        ticket("t1", kind="return_refund", detail={"refundId": "r1"}),
        ticket("t2", kind="return_refund", detail={"refundId": "r2"}),
    ])
    assert [s.kind for s in signals] == [Kind.REPEATED_REFUND]


def test_multiple_orders_keep_all_evidence_without_an_arbitrary_first_order():
    signals = kinds(tickets=[
        ticket(f"{order}-{i}", order=order, detail={"paymentType": "退款"})
        for order in ["order1", "order2"] for i in range(2)
    ])
    assert len(signals) == 1
    assert signals[0].order_ids == ["order1", "order2"]
    assert len(signals[0].evidence) == 4


def test_source_overdue_uses_snapshot_clock_not_current_wall_clock():
    evidence = [msg(body="怎么还没处理", hours=1)]
    assert not kinds(evidence, [ticket(kind="logistics")], source_clock=START + timedelta(hours=47))
    signals = kinds(evidence, [ticket(kind="logistics")], source_clock=START + timedelta(hours=48))
    assert [s.kind for s in signals] == [Kind.WORK_ORDER_OVERDUE]


def test_local_deadline_does_not_require_a_customer_to_complain():
    signals = kinds(tickets=[ticket(kind="logistics", is_source=False, local_status="in_progress",
                                   due_at=START + timedelta(hours=1))])
    assert [s.kind for s in signals] == [Kind.WORK_ORDER_OVERDUE]
    assert signals[0].conditions["basis"] == "explicit_followup_deadline"
    assert not kinds(tickets=[ticket(kind="logistics", is_source=False, local_status="resolved",
                                    due_at=START + timedelta(hours=1))])


def test_latest_escalation_is_observed_and_calm_followup_is_not_automatic_closure():
    signals = kinds([msg(), msg(body="我要投诉", hours=1), msg(body="已经解决了，谢谢", hours=2)])
    assert all(not s.active for s in signals)


def test_simple_emotion_escalation_is_low_risk_and_pursuit_is_medium():
    low = next(signal for signal in kinds([
        msg(body="查询进度"),
        msg(body="钱要定了", hours=1),
    ]) if signal.kind == Kind.EMOTION_ESCALATION)
    medium = next(signal for signal in kinds([
        msg(body="查询进度"),
        msg(body="怎么还没处理好，钱要定了", hours=1),
    ]) if signal.kind == Kind.EMOTION_ESCALATION)
    assert low.level.value == "low"
    assert medium.level.value == "medium"
    repeated = kinds([msg(), msg(body="我要投诉", hours=1), msg(body="已经解决了，谢谢", hours=2),
                      msg(body="又没处理好，我要再次投诉", hours=3)])
    escalation = next(s for s in repeated if s.kind == Kind.EMOTION_ESCALATION)
    assert escalation.at == START + timedelta(hours=3)
    assert escalation.active


def test_calm_follow_up_without_resolved_words_clears_escalation_and_complaint():
    signals = kinds([msg(), msg(body="我要投诉", hours=1), msg(body="嗯，这还差不多", hours=2)])
    assert all(not signal.active for signal in signals)
    assert all(signal.conditions["clearReason"] == "consumer_calm_follow_up" for signal in signals)


def test_calm_follow_up_does_not_clear_a_new_unresolved_pursuit():
    signals = kinds([msg(), msg(body="我要投诉", hours=1), msg(body="嗯，这还差不多，不过还没退款", hours=2)])
    assert any(signal.kind == Kind.COMPLAINT_RISK and signal.active for signal in signals)


def test_completed_record_conflict_clears_only_after_explicit_resolution_feedback():
    completed = ticket(
        kind="logistics", completed_at=START + timedelta(hours=1),
    )
    history = [msg(), msg(body="怎么还没处理好", hours=2)]
    unresolved = kinds(history, [completed])
    assert next(s for s in unresolved if s.kind == Kind.DATA_CONFLICT).active
    calm = kinds([*history, msg(body="嗯，这还差不多", hours=3)], [completed])
    assert next(s for s in calm if s.kind == Kind.DATA_CONFLICT).active
    resolved = kinds([*history, msg(body="已经解决了，谢谢", hours=3)], [completed])
    signal = next(s for s in resolved if s.kind == Kind.DATA_CONFLICT)
    assert not signal.active
    assert signal.conditions["clearReason"] == "consumer_resolved_follow_up"
    assert signal.evidence[-1].body == "已经解决了，谢谢"


def test_escalation_retains_the_strongest_evidence_until_an_explicit_relief():
    signals = kinds([msg(), msg(body="我要投诉", hours=1),
                     msg(body="钱要定了，别想赖", hours=2)])
    escalation = next(s for s in signals if s.kind == Kind.EMOTION_ESCALATION)
    assert escalation.level.value == "high"
    assert escalation.at == START + timedelta(hours=2)
    assert any("投诉" in e.body for e in escalation.evidence)


@pytest.mark.parametrize("body", ["不用投诉了", "我不是来投诉的", "不需要投诉", "我不再投诉"])
def test_negated_complaint_does_not_trigger(body):
    assert not kinds([msg(), msg(body=body, hours=1)])


def local_message(seconds=0, role="customer", body="请核对订单", *, closed_at=None):
    return RuleMessage(
        f"{role}-{seconds}", "c1", "buyer", body, START + timedelta(seconds=seconds),
        sender_role=role, is_source=False, service_closed_at=closed_at,
    )


@pytest.mark.parametrize("elapsed, expected", [(119, False), (120, True), (121, True)])
def test_response_wait_detects_before_complaint_at_configured_boundary(elapsed, expected):
    signals = kinds([local_message()], now=START + timedelta(seconds=elapsed))
    assert any(signal.kind == Kind.RESPONSE_WAIT for signal in signals) is expected
    assert not any(signal.kind == Kind.COMPLAINT_RISK for signal in signals)


def test_customer_follow_up_does_not_reset_wait_and_system_notice_is_not_a_reply():
    history = [
        local_message(), local_message(100, body="在吗"),
        local_message(110, role="system", body="已转人工"),
    ]
    waiting = next(signal for signal in kinds(history, now=START + timedelta(seconds=121))
                   if signal.kind == Kind.RESPONSE_WAIT)
    assert waiting.conditions["waitingSince"] == START.isoformat() + "+00:00"
    assert waiting.at == START + timedelta(seconds=120)
    assert {item.ref for item in waiting.evidence} == {"customer-0", "customer-100"}


@pytest.mark.parametrize("role", ["operator", "assistant"])
def test_actual_service_reply_clears_wait_without_counting_staff_emotion(role):
    assert not kinds(
        [local_message(), local_message(121, role=role, body="投诉风险由客服核对")],
        now=START + timedelta(seconds=122),
    )


def test_historical_import_closed_service_and_short_acknowledgement_do_not_wait():
    assert not kinds([msg()], now=START + timedelta(days=365))
    assert not kinds([local_message(closed_at=START + timedelta(seconds=30))],
                     now=START + timedelta(seconds=121))
    assert not kinds([local_message(), local_message(60, body="好的，谢谢")],
                     now=START + timedelta(seconds=121))
    fresh = kinds([
        local_message(closed_at=START + timedelta(seconds=30)),
        local_message(100, body="再查另一笔订单", closed_at=START + timedelta(seconds=30)),
    ], now=START + timedelta(seconds=221))
    waiting = next(signal for signal in fresh if signal.kind == Kind.RESPONSE_WAIT)
    assert waiting.at == START + timedelta(seconds=220)


@pytest.mark.parametrize("minutes, expected", [(31, False), (30, True), (1, True)])
def test_followup_warning_precedes_deadline_without_complaint(minutes, expected):
    now = START + timedelta(hours=1)
    pending = ticket(kind="logistics", local_status="in_progress", is_source=False,
                     due_at=now + timedelta(minutes=minutes))
    signals = kinds(tickets=[pending], now=now)
    assert any(signal.kind == Kind.FOLLOWUP_DUE_SOON for signal in signals) is expected
    assert not any(signal.kind == Kind.WORK_ORDER_OVERDUE for signal in signals)


def test_due_soon_retains_all_deadlines_and_is_replaced_by_overdue():
    now = START + timedelta(hours=1)
    tickets = [
        ticket(f"t-{minutes}", kind="logistics", local_status="in_progress", is_source=False,
               due_at=now + timedelta(minutes=minutes))
        for minutes in [10, 20]
    ]
    warning = next(signal for signal in kinds(tickets=tickets, now=now)
                   if signal.kind == Kind.FOLLOWUP_DUE_SOON)
    assert len(warning.conditions["deadlines"]) == 2 and len(warning.evidence) == 4
    elapsed = kinds(tickets=tickets, now=now + timedelta(minutes=20))
    assert {signal.kind for signal in elapsed} == {Kind.WORK_ORDER_OVERDUE}


def test_early_warning_thresholds_can_be_disabled():
    now = START + timedelta(hours=1)
    signals = compute_signals(
        [local_message()],
        [ticket(kind="logistics", local_status="in_progress", is_source=False,
                due_at=now + timedelta(minutes=10))],
        now=now, source_clock=None, response_wait_seconds=0, followup_warning_minutes=0,
    )
    assert not signals
