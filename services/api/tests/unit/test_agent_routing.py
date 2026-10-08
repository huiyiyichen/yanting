"""分流策略与理解模块测试。

覆盖官方难点三（分流）、四（接稳）与五（幻觉）的规则边界，
以及 PRD AC-06（情绪策略匹配率 100%、单纯愤怒不转后台）。
"""

from __future__ import annotations

import pytest

from app.domain.agent.contracts import CaseFacts
from app.domain.agent.routing import (
    MAX_CLARIFICATION_ATTEMPTS,
    ROUTE_DEALER_VERIFICATION,
    ROUTE_HUMAN_REVIEW,
    ROUTE_REQUEST_DRAFT,
    ROUTE_TROUBLESHOOTING,
    ROUTE_WARRANTY_CHECK,
    communication_style_for,
    decide_route,
    primary_request_type,
    sort_intents,
)
from app.domain.agent.understanding import (
    _resolve_intents,
    extract_json,
    resolve_country,
)
from app.domain.enums import (
    ComplaintRisk,
    CustomerIntent,
    DealerAuthorizationStatus,
    EmotionLevel,
    FaultType,
    KnowledgeHitStatus,
    RequestType,
    WarrantyStatus,
)
from app.errors import ModelOutputInvalid

COMPLETE_FACTS = CaseFacts(
    product_model="A1 Pro",
    country_code="CN",
    purchase_channel="official_website",
)


class TestEmotionPolicy:
    def test_all_four_emotions_have_distinct_styles(self) -> None:
        """AC-06：四类情绪必须映射到不同沟通策略。"""

        styles = {
            communication_style_for(emotion)
            for emotion in (
                EmotionLevel.CALM,
                EmotionLevel.DISSATISFIED,
                EmotionLevel.ANGRY,
                EmotionLevel.UNKNOWN,
            )
        }
        assert len(styles) == 4

    def test_anger_alone_does_not_escalate_to_human(self) -> None:
        """核心规则：单纯愤怒不触发转接，Agent 先安抚并继续处理。"""

        decision = decide_route(
            facts=COMPLETE_FACTS,
            intents=[CustomerIntent.DIAGNOSIS],
            emotion=EmotionLevel.ANGRY,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
        )
        assert decision.human_intervention_required is False
        assert decision.route == ROUTE_TROUBLESHOOTING
        assert decision.communication_style == "brief_reassure_then_solve"

    def test_anger_with_high_risk_intent_still_generates_draft_not_escalation(self) -> None:
        """愤怒 + 退款诉求仍然走草稿路径，不因情绪直接转人工。"""

        decision = decide_route(
            facts=COMPLETE_FACTS,
            intents=[CustomerIntent.REFUND],
            emotion=EmotionLevel.ANGRY,
            complaint_risk=ComplaintRisk.FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
        )
        assert decision.route == ROUTE_REQUEST_DRAFT
        assert decision.human_intervention_required is False

    def test_complaint_risk_does_not_trigger_escalation_by_itself(self) -> None:
        decision = decide_route(
            facts=COMPLETE_FACTS,
            intents=[CustomerIntent.DIAGNOSIS],
            emotion=EmotionLevel.DISSATISFIED,
            complaint_risk=ComplaintRisk.FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
        )
        assert decision.human_intervention_required is False


class TestMissingFacts:
    def test_missing_product_asks_before_acting(self) -> None:
        facts = CaseFacts(country_code="CN")
        decision = decide_route(
            facts=facts,
            intents=[CustomerIntent.REFUND],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
        )
        assert "ask_clarification" in decision.allowed_actions
        # 关键事实缺失时绝不能进入申请草稿路径
        assert decision.route != ROUTE_REQUEST_DRAFT

    def test_missing_country_asks_before_acting(self) -> None:
        facts = CaseFacts(product_model="A1 Pro")
        decision = decide_route(
            facts=facts,
            intents=[CustomerIntent.REPLACEMENT],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
        )
        assert decision.route != ROUTE_REQUEST_DRAFT

    def test_repeated_clarification_escalates(self) -> None:
        """同一必要事实连续澄清两轮仍无新增信息时停止重复追问。"""

        facts = CaseFacts()
        decision = decide_route(
            facts=facts,
            intents=[CustomerIntent.DIAGNOSIS],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
            clarification_attempts=MAX_CLARIFICATION_ATTEMPTS,
        )
        assert decision.route == ROUTE_HUMAN_REVIEW
        assert decision.human_intervention_required is True

    def test_first_clarification_does_not_escalate(self) -> None:
        decision = decide_route(
            facts=CaseFacts(),
            intents=[CustomerIntent.DIAGNOSIS],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
            clarification_attempts=1,
        )
        assert decision.human_intervention_required is False


class TestEvidenceBoundary:
    def test_no_knowledge_with_high_risk_intent_escalates(self) -> None:
        """检索不到依据时不得自由生成承诺（AC-09）。"""

        decision = decide_route(
            facts=COMPLETE_FACTS,
            intents=[CustomerIntent.REFUND],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.NOT_FOUND,
        )
        assert decision.route == ROUTE_HUMAN_REVIEW
        assert decision.human_intervention_required is True

    def test_no_knowledge_for_diagnosis_does_not_escalate_immediately(self) -> None:
        """一次未命中不等于立即转人工：先补问/补查。"""

        decision = decide_route(
            facts=COMPLETE_FACTS,
            intents=[CustomerIntent.DIAGNOSIS],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.NOT_FOUND,
        )
        assert decision.human_intervention_required is False

    def test_conflicting_evidence_escalates(self) -> None:
        decision = decide_route(
            facts=COMPLETE_FACTS,
            intents=[CustomerIntent.DIAGNOSIS],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.CONFLICTING,
        )
        assert decision.route == ROUTE_HUMAN_REVIEW
        assert decision.human_intervention_reason == "conflicting_evidence"


class TestDealerRoute:
    def test_third_party_channel_needs_verification(self) -> None:
        facts = CaseFacts(
            product_model="A1 Pro",
            country_code="CN",
            purchase_channel="third_party_seller",
            seller_name_raw="某第三方店铺",
        )
        decision = decide_route(
            facts=facts,
            intents=[CustomerIntent.WARRANTY_CHECK],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
            dealer_status=DealerAuthorizationStatus.UNKNOWN,
        )
        assert decision.route == ROUTE_DEALER_VERIFICATION
        assert "dealer_lookup" in decision.allowed_actions

    def test_official_channel_skips_dealer_verification(self) -> None:
        """官方渠道不执行经销商核验：不是每位用户的必填步骤。"""

        decision = decide_route(
            facts=COMPLETE_FACTS,
            intents=[CustomerIntent.WARRANTY_CHECK],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
            dealer_status=None,
        )
        assert decision.route == ROUTE_WARRANTY_CHECK

    def test_query_failed_does_not_become_not_authorized(self) -> None:
        facts = CaseFacts(
            product_model="A1 Pro",
            country_code="US",
            purchase_channel="third_party_seller",
            seller_name_raw="QuickBuy Deals",
        )
        decision = decide_route(
            facts=facts,
            intents=[CustomerIntent.WARRANTY_CHECK],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
            dealer_status=DealerAuthorizationStatus.QUERY_FAILED,
        )
        assert decision.route == ROUTE_DEALER_VERIFICATION


class TestRouteSelection:
    def test_refund_intent_routes_to_draft(self) -> None:
        decision = decide_route(
            facts=COMPLETE_FACTS,
            intents=[CustomerIntent.REFUND],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
        )
        assert decision.route == ROUTE_REQUEST_DRAFT
        assert "create_request_draft" in decision.allowed_actions

    def test_warranty_intent_routes_to_warranty_check(self) -> None:
        decision = decide_route(
            facts=COMPLETE_FACTS,
            intents=[CustomerIntent.WARRANTY_CHECK],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
        )
        assert decision.route == ROUTE_WARRANTY_CHECK
        assert "warranty_evaluate" in decision.allowed_actions

    def test_warranty_query_failure_is_recorded_not_judged(self) -> None:
        decision = decide_route(
            facts=COMPLETE_FACTS,
            intents=[CustomerIntent.WARRANTY_CHECK],
            emotion=EmotionLevel.CALM,
            complaint_risk=ComplaintRisk.NOT_FLAGGED,
            knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
            warranty_status=WarrantyStatus.QUERY_FAILED,
        )
        assert any("查询失败" in note for note in decision.notes)


class TestIntentHandling:
    def test_primary_request_type_priority(self) -> None:
        intents = [CustomerIntent.PARTS, CustomerIntent.REFUND, CustomerIntent.DIAGNOSIS]
        assert primary_request_type(intents) is RequestType.REFUND

    def test_no_high_risk_intent_returns_none(self) -> None:
        assert primary_request_type([CustomerIntent.DIAGNOSIS]) is None

    def test_sort_keeps_all_intents(self) -> None:
        intents = [
            CustomerIntent.DIAGNOSIS,
            CustomerIntent.REFUND,
            CustomerIntent.COMPLAINT,
        ]
        ordered = sort_intents(intents)
        assert set(ordered) == set(intents)
        assert ordered[0] is CustomerIntent.COMPLAINT

    def test_keyword_fallback_adds_obvious_intents(self) -> None:
        resolved = _resolve_intents([], "我不要了，能退款吗？")
        assert CustomerIntent.REFUND in resolved

    def test_keyword_fallback_detects_complaint(self) -> None:
        resolved = _resolve_intents([], "再不解决我就去投诉了")
        assert CustomerIntent.COMPLAINT in resolved

    def test_unknown_when_nothing_detected(self) -> None:
        resolved = _resolve_intents([], "你好")
        assert resolved == [CustomerIntent.UNKNOWN]

    def test_invalid_model_intent_is_dropped_not_guessed(self) -> None:
        resolved = _resolve_intents(["refund", "totally_made_up"], "我要退款")
        assert CustomerIntent.REFUND in resolved
        assert len(resolved) == 1


class TestJsonExtraction:
    def test_plain_json(self) -> None:
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_fenced_json(self) -> None:
        assert extract_json('```json\n{"a": 2}\n```') == {"a": 2}

    def test_json_with_prose_is_extracted(self) -> None:
        assert extract_json('好的，结果如下：{"a": 3} 以上。') == {"a": 3}

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(ModelOutputInvalid):
            extract_json("完全没有 JSON")

    def test_non_object_json_raises(self) -> None:
        with pytest.raises(ModelOutputInvalid):
            extract_json("[1, 2, 3]")


class TestCountryResolution:
    def test_chinese_names(self) -> None:
        assert resolve_country("中国大陆") == "CN"
        assert resolve_country("美国") == "US"

    def test_iso_codes(self) -> None:
        assert resolve_country("DE") == "DE"

    def test_unrecognized_returns_none(self) -> None:
        assert resolve_country("火星") is None

    def test_empty_returns_none(self) -> None:
        assert resolve_country("") is None


class TestFactsMissing:
    def test_complete_facts_have_no_missing(self) -> None:
        assert COMPLETE_FACTS.missing_required() == []

    def test_missing_both(self) -> None:
        assert set(CaseFacts().missing_required()) == {"product_model", "country_code"}

    def test_fault_type_defaults_to_unknown(self) -> None:
        assert CaseFacts().fault_type is FaultType.UNKNOWN
