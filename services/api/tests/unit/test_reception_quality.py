import json

import pytest

from app.evaluation.reception_quality import (
    blind_review_packet,
    conversation_for_turn,
    prior_case_exposure,
    summarize_cases,
    turn_checks,
)


def test_memory_category_and_quote_checks_require_verified_current_memory():
    spec = {"expectedMode": "autonomous", "expectModelReply": True,
            "memoryCriteria": [{"category": "known", "alternatives": ["混合偏干"]}]}
    observed = {
        "mode": "autonomous", "reply": ["已经记录您的更正"],
        "assistant": {"isMock": False, "stale": False},
        "memory": {"verified": False, "items": [{"category": "known", "quote": "混合偏干"}]},
    }
    assert turn_checks(spec, observed)["quotedMemory:1"] is False
    observed["memory"]["verified"] = True
    assert all(turn_checks(spec, observed).values())


def test_handoff_does_not_need_a_new_model_reply_and_late_reply_fails():
    spec = {"expectedMode": "operator_assisted", "expectModelReply": False}
    observed = {"mode": "operator_assisted", "reply": [], "assistant": None}
    assert all(turn_checks(spec, observed).values())
    observed["reply"] = ["迟到回复"]
    assert not turn_checks(spec, observed)["newModelReply"]


def test_failed_run_costs_and_incomplete_cases_are_not_hidden():
    cases = [{"plannedTurns": 2, "turns": [
        {"checks": {"mode": True}, "elapsedSeconds": 3},
    ], "runHistory": [
        {"status": "failed", "usage": {"calls": 2, "promptTokens": 100, "completionTokens": 20}},
        {"status": "success", "usage": {"calls": 2, "promptTokens": 80, "completionTokens": 10}},
    ]}]
    summary = summarize_cases(cases)
    assert summary["casesAllMechanicalChecks"] == 0
    assert summary["failedRuns"] == 1
    assert summary["modelCalls"] == 4 and summary["promptTokens"] == 180
    cases[0]["runHistory"][0]["usage"]["promptTokens"] = None
    summary = summarize_cases(cases)
    assert summary["promptTokens"] is None and summary["usageUnknownRuns"] == 1


def test_review_packet_does_not_leak_generator_validation_or_mechanical_pass_flags():
    packet = blind_review_packet({"rubric": {"context": "retain corrections"}}, [{
        "id": "Q1", "topic": "肤质纠正", "semanticGoals": ["使用最新自述"],
        "turns": [{"customer": "更正我是混合偏干", "reply": ["已记录更正"],
                   "expectModelReply": True, "checks": {"mode": True},
                   "assistant": {"verificationStatus": "verified", "claims": []}}],
    }])
    turn = packet["cases"][0]["turns"][0]
    assert "checks" not in turn and "assistant" not in turn
    assert packet["rubric"]["context"] == "retain corrections"


def test_missing_rubric_does_not_lose_a_failed_dialogue_or_invent_a_score():
    packet = blind_review_packet({}, [{
        "id": "CN01", "topic": "国内商品资料核对", "semanticGoals": ["使用对应商品依据"],
        "turns": [{"customer": "比较两款商品", "reply": [],
                   "mode": "operator_assisted", "expectModelReply": True}],
    }])
    assert packet["rubric"] == {}
    assert packet["rubricStatus"] == "missing_no_numeric_score"
    assert packet["cases"][0]["turns"][0]["reply"] == []


def test_previously_observed_tasks_are_identified_without_treating_review_artifacts_as_runs(tmp_path):
    (tmp_path / "loreal-reception-quality-run.json").write_text(json.dumps({
        "caseSha256": "frozen", "configurationBefore": {},
        "cases": [{"id": "Q1", "turns": [{"reply": []}]}, {"id": "Q2", "turns": []}],
    }), encoding="utf-8")
    (tmp_path / "loreal-reception-quality-run-review.json").write_text(json.dumps({
        "caseSha256": "frozen", "cases": [{"id": "Q3", "turns": [{}]}],
    }), encoding="utf-8")
    assert prior_case_exposure(tmp_path, "frozen") == ["Q1"]
    assert prior_case_exposure(tmp_path, "other") == []


def test_named_sessions_share_only_the_declared_customer_scope_and_reuse_the_same_conversation():
    creates = []

    def api(method, route, role, payload):
        assert method == "POST" and route == "/api/customer/conversations" and role == "customer"
        creates.append(payload)
        return {"conversationId": f"conv-{len(creates)}"}

    sessions = {}
    first = conversation_for_turn(api, sessions, {"session": "initial"}, "run", "H01")
    followup = conversation_for_turn(api, sessions, {"session": "followup"}, "run", "H01")
    assert first != followup
    assert creates[0]["customerId"] == creates[1]["customerId"]
    assert conversation_for_turn(api, sessions, {"session": "followup"}, "run", "H01") == followup
    foreign = conversation_for_turn(api, sessions, {"session": "foreign", "customerScope": "other"}, "run", "H01")
    assert foreign not in {first, followup}
    assert creates[-1]["customerId"] != creates[0]["customerId"]
    with pytest.raises(ValueError):
        conversation_for_turn(api, sessions, {"session": "followup", "customerScope": "other"}, "run", "H01")


@pytest.mark.parametrize("reply, matches", [
    ("第一笔98元，第二笔1598元。", True),
    ("98.00元", True),
    ("只有1598元", False),
    ("98.50元", False),
])
def test_numeric_word_checks_do_not_find_98_inside_1598_or_a_different_amount(reply, matches):
    checks = turn_checks({"expectedMode": "autonomous", "expectModelReply": True,
                          "replyRequired": ["98"]},
                         {"mode": "autonomous", "reply": [reply],
                          "assistant": {"isMock": False, "stale": False}})
    assert checks["replyContains:98"] is matches


def test_missing_service_analysis_does_not_count_as_a_verified_no_breakpoint_result():
    spec = {"expectedMode": "autonomous", "expectModelReply": True, "breakpointExpectation": "none"}
    observed = {"mode": "autonomous", "reply": ["不重复追问"], "assistant": {"isMock": False, "stale": False}}
    assert turn_checks(spec, observed)["currentBreakpointAnalysis"] is False
    observed["breakpointAssessment"] = {"analyzed": True, "stale": False, "findings": []}
    assert all(turn_checks(spec, observed).values())


def test_foreign_customer_text_is_checked_in_replies_memory_and_sources():
    spec = {"expectedMode": "autonomous", "expectModelReply": True,
            "replyForbidden": ["专属关注"], "forbiddenMemoryText": ["专属关注"],
            "forbiddenSourceText": ["专属关注"]}
    observed = {
        "mode": "autonomous", "reply": ["不会继承专属关注"],
        "assistant": {"isMock": False, "stale": False, "groundingSources": [{"text": "专属关注"}]},
        "memory": {"items": [{"quote": "专属关注"}]},
    }
    checks = turn_checks(spec, observed)
    assert checks["replyExcludes:专属关注"] is False
    assert checks["memoryExcludes:专属关注"] is False
    assert checks["sourcesExcludes:专属关注"] is False
