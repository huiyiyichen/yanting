from types import SimpleNamespace

import pytest

from app.domain.consumer_service.service_breakpoints import promise_deadline, qualify_findings
from app.schemas.grounding import GroundingSource
from app.schemas.service_breakpoints import BreakpointCandidate


def source(ref, kind, text, at="2026-05-01T08:00:00", subject="c1", **fields):
    return GroundingSource(source_id=ref, kind=kind, subject_id=subject, label=ref,
                           text=text, occurred_at=at, fields=fields)


def context():
    return SimpleNamespace(conversation_id="c1", orders=[], work_orders=[])


def repeated():
    sources = [
        source("m1", "customer_message", "想知道物流有没有进展"),
        source("m2", "customer_message", "物流还是没有变化，请帮我核对", "2026-05-01T09:00:00"),
    ]
    candidate = BreakpointCandidate(kind="repeated_question", topic="物流进度", reason="消费者重复询问同一诉求",
                                    evidence=[{"source_ref": s.source_id, "quote": s.text} for s in sources])
    return sources, candidate


def test_repeated_questions_require_distinct_current_evidence_and_a_bounded_window():
    sources, candidate = repeated()
    findings, issues = qualify_findings([candidate], sources, [], context())
    assert not issues and len(findings) == 1
    assert findings[0].detected_at == "2026-05-01T01:00:00+00:00"
    candidate.evidence[0].source_ref = "m2"
    candidate.evidence[0].quote = sources[1].text
    assert qualify_findings([candidate], sources, [], context())[1]


@pytest.mark.parametrize("last_at, accepted", [
    ("2026-05-04T08:00:00", True), ("2026-05-04T08:00:01", False),
])
def test_repeat_window_uses_event_time_not_the_current_machine_date(last_at, accepted):
    sources, candidate = repeated()
    sources[1].occurred_at = last_at
    assert (not qualify_findings([candidate], sources, [], context())[1]) is accepted


def test_fabricated_quotes_unrelated_customers_and_different_orders_are_rejected():
    sources, candidate = repeated()
    candidate.evidence[0].quote = "不存在的描述"
    assert qualify_findings([candidate], sources, [], context())[1]
    candidate.evidence[0].quote = sources[0].text
    sources[0].subject_id = "another-customer"
    assert qualify_findings([candidate], sources, [], context())[1]
    sources[0].subject_id = "c1"
    sources[0].text = candidate.evidence[0].quote = "订单111111的物流"
    sources[1].text = candidate.evidence[1].quote = "订单222222的物流"
    assert qualify_findings([candidate], sources, [], context())[1]


@pytest.mark.parametrize("promise, last_at, accepted", [
    ("48小时内给您答复", "2026-05-03T08:00:01", True),
    ("48小时内给您答复", "2026-05-03T08:00:00", False),
    ("尽快给您答复", "2026-05-10T08:00:00", False),
    ("24小时内或48小时内给您答复", "2026-05-10T08:00:00", False),
])
def test_promise_qualification_requires_an_explicit_deadline_and_later_feedback(promise, last_at, accepted):
    staff = source("staff", "staff_message", promise)
    customer = source("customer", "customer_message", "还没有等到答复", last_at)
    candidate = BreakpointCandidate(
        kind="unmet_promise", topic="答复承诺", reason="消费者反馈尚未收到答复，需要核实",
        promise_ref="staff", evidence=[{"source_ref": s.source_id, "quote": s.text} for s in [staff, customer]],
    )
    findings, issues = qualify_findings([candidate], [staff, customer], [], context())
    assert (not issues) is accepted
    if accepted:
        assert findings[0].promise_due_at == "2026-05-03T00:00:00+00:00"


def test_absolute_promise_date_is_local_day_end_and_invalid_dates_are_not_guessed():
    staff = source("staff", "staff_message", "2026年5月3日答复")
    assert promise_deadline(staff, staff.text).isoformat() == "2026-05-03T15:59:59+00:00"
    assert promise_deadline(staff, "2026年2月31日答复") is None


@pytest.mark.parametrize("status, completed_at, feedback_at, accepted", [
    ("已完结", "2026-05-02T08:00:00", "2026-05-02T09:00:00", True),
    ("进行中", "2026-05-02T08:00:00", "2026-05-02T09:00:00", False),
    ("已完结", None, "2026-05-02T09:00:00", False),
    ("已完结", "2026-05-02T10:00:00", "2026-05-02T09:00:00", False),
])
def test_resolution_mismatch_needs_a_completed_record_and_post_completion_customer_report(
    status, completed_at, feedback_at, accepted,
):
    work = source("work", "work_order", f"源记录状态：{status}", sourceStatus=status,
                  completedAt=completed_at, workOrderId="WO-1")
    customer = source("customer", "customer_message", "包装破损的问题还没有解决", feedback_at)
    candidate = BreakpointCandidate(
        kind="resolution_mismatch", topic="破损处理", reason="工单记录与消费者反馈需要核实",
        state_ref="work", evidence=[{"source_ref": s.source_id, "quote": s.text} for s in [work, customer]],
    )
    assert (not qualify_findings([candidate], [work, customer], [], context())[1]) is accepted


def test_ai_statement_is_not_a_completed_business_record():
    staff = source("staff", "staff_message", "已经完成处理", localStatus="resolved")
    customer = source("customer", "customer_message", "还没解决", "2026-05-02T09:00:00")
    candidate = BreakpointCandidate(
        kind="resolution_mismatch", topic="处理结果", reason="待核实",
        state_ref="staff", evidence=[{"source_ref": s.source_id, "quote": s.text} for s in [staff, customer]],
    )
    assert qualify_findings([candidate], [customer], [staff], context())[1]
