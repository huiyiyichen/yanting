from types import SimpleNamespace

from app.domain.consumer_service import incidents
from app.domain.consumer_service.incidents import _legacy_contact_context, _triage_priority
from app.domain.enums import ServiceRiskLevel, ServiceRiskStatus, ServiceRiskType


def signal(kind, level, *, active=True, analysis_stale=False, status="pending"):
    return SimpleNamespace(
        risk_type=ServiceRiskType(kind), risk_level=ServiceRiskLevel(level),
        risk_status=ServiceRiskStatus(status),
        signal_active=active, conditions={"analysisStale": analysis_stale},
    )


def test_triage_priority_separates_operator_attention_from_risk_status():
    score, label, reasons = _triage_priority(
        [
            signal("adverse_reaction", "high"),
            signal("service_breakpoint", "medium"),
        ],
        status="pending", open_ticket_count=0, needs_review=True,
        recurrence_count=1, signal_active=True,
    )
    assert label == "urgent"
    assert score <= 100
    assert {"高风险", "不良反应", "服务断点", "复发1次", "待人工复核", "尚无进行中工单", "尚未介入"} <= set(reasons)

    score, label, reasons = _triage_priority(
        [signal("service_breakpoint", "low", active=False)],
        status="pending", open_ticket_count=1, needs_review=True,
        recurrence_count=0, signal_active=False,
    )
    assert label == "review"
    assert score < 70
    assert "暂无当前有效触发" in reasons


def test_closed_and_stale_signals_cannot_raise_current_priority():
    closed = signal("adverse_reaction", "high", status="resolved")
    score, label, reasons = _triage_priority(
        [closed], status="resolved", open_ticket_count=0, needs_review=False,
        recurrence_count=10, signal_active=True,
    )
    assert (score, label, reasons) == (0, "normal", ["已关闭"])
    stale = signal("service_breakpoint", "high", analysis_stale=True)
    score, label, reasons = _triage_priority(
        [stale, closed], status="pending", open_ticket_count=0, needs_review=True,
        recurrence_count=10, signal_active=False,
    )
    assert label == "review" and score == 10
    assert "高风险" not in reasons


def test_historical_sensitivity_adds_attention_reason_without_changing_risk_state():
    score, label, reasons = _triage_priority(
        [signal("response_wait", "medium")],
        status="pending", open_ticket_count=0, needs_review=False,
        recurrence_count=0, signal_active=True, historical_sensitivity=2,
    )
    assert score == 30 + 8 + 8 + 5 + 8
    assert label == "priority"
    assert "历史风险敏感度2/3" in reasons


def test_legacy_repeated_contact_reconstructs_history_evidence_without_window_claim(monkeypatch):
    sender = SimpleNamespace(value="customer")
    messages = {
        "S00146": [SimpleNamespace(
            sender_role=sender, body="嗯，这还差不多", message_id="m-current",
            created_at="2026-05-11T10:25:28+08:00",
        )],
        "S00029": [SimpleNamespace(
            sender_role=sender, body="之前也来问过退货", message_id="m-history",
            created_at="2026-05-06T06:24:56+08:00",
        )],
    }
    monkeypatch.setattr(incidents, "_messages", lambda _session, conversation_id: messages[conversation_id])
    signal_row = SimpleNamespace(
        risk_type=ServiceRiskType.REPEATED_CONTACT, rule_version="legacy",
        conversation_id="S00146",
    )
    context = SimpleNamespace(conversation_id="S00146", history_conversation_ids=["S00029"])

    evidence, conditions = _legacy_contact_context(None, signal_row, [context])

    assert [item.ref for item in evidence] == ["m-current", "m-history"]
    assert all(item.kind == "history_context" for item in evidence)
    assert conditions == {
        "basis": "legacy_context_history",
        "contactCount": 2,
        "conversationIds": ["S00146", "S00029"],
    }
