import pytest

from app.domain.consumer_service.personalization import (
    AdviceCandidate,
    advice_views,
    validate_advice,
    validate_care_preferences,
)
from app.schemas.grounding import GroundingSource


def source(source_id, kind, text, fields=None):
    return GroundingSource(
        source_id=source_id, kind=kind, subject_id=source_id,
        label=f"label-{source_id}", text=text, fields=fields or {},
    )


def catalog():
    return {
        "m1": source("m1", "customer_message", "T区容易出油，两颊偏干，我更在意粉底服帖。"),
        "k1": source(
            "k1", "knowledge", "非具体商品依据：油性区域温和清洁，干燥区域注意保湿。",
            {"scope": "general_consumer"},
        ),
    }


def candidate(**changes):
    return AdviceCandidate.model_validate({
        "category": "routine", "title": "分区护理",
        "action": "T区避免过度清洁；两颊干燥时注意保湿。",
        "rationale": "按你描述的分区使用感受调整，不按爆款推荐。",
        "evidence": [
            {"source_ref": "m1", "quote": "T区容易出油，两颊偏干"},
            {"source_ref": "k1", "quote": "油性区域温和清洁，干燥区域注意保湿"},
        ],
        **changes,
    })


def validate(items, sources=None, **changes):
    return validate_advice(
        items, sources or catalog(),
        **{"intent": "product_question", "handoff_required": False,
           "latest_message": "不要推荐品牌，想要通用护理方案。", **changes},
    )


def test_cited_routine_is_rendered_without_truncating_relevant_evidence():
    item = candidate()
    assert validate([item]) == []
    view = advice_views([item], catalog())[0]
    assert view.scope == "general_consumer"
    assert view.evidence[1].quote == item.evidence[1].quote
    assert view.evidence[1].label == "label-k1"


@pytest.mark.parametrize("evidence", [
    [{"source_ref": "missing", "quote": "肤质"}, {"source_ref": "k1", "quote": "温和清洁"}],
    [{"source_ref": "m1", "quote": "两颊敏感"}, {"source_ref": "k1", "quote": "温和清洁"}],
    [{"source_ref": "m1", "quote": "两颊偏干"}, {"source_ref": "m1", "quote": "容易出油"}],
    [{"source_ref": "k1", "quote": "温和清洁"}, {"source_ref": "k1", "quote": "保湿"}],
])
def test_fabricated_or_one_sided_evidence_is_rejected(evidence):
    assert validate([candidate(evidence=evidence)])


def test_orders_and_catalog_unknowns_do_not_establish_skin_care_guidance():
    sources = catalog()
    sources["k1"] = source("k1", "order", "油性区域温和清洁，干燥区域注意保湿")
    assert validate([candidate()], sources)
    sources["k1"] = source(
        "k1", "knowledge", "油性区域温和清洁，干燥区域注意保湿",
        {"scope": "document_context"},
    )
    assert validate([candidate()], sources)


@pytest.mark.parametrize("changes", [
    {"intent": "logistics"},
    {"intent": "adverse_reaction"},
    {"handoff_required": True},
])
def test_old_advice_does_not_continue_after_topic_change_or_handoff(changes):
    assert validate([candidate()], **changes)
    assert validate([], **changes) == []


def test_no_brand_preference_is_not_treated_as_a_product_request():
    assert validate([candidate(
        category="product_selection", action="先提供品牌和货号资料。",
    )])
    assert validate([candidate(category="makeup")]) == []
    assert validate([candidate(
        category="product_selection", action="按油性区域需求核对oil-free标签，不推荐品牌。",
    )]) == []
    assert validate(
        [candidate(category="product_selection")],
        latest_message="请给我通用选择维度，不需要保证任何商品适用。",
    ) == []


def test_general_knowledge_cannot_support_a_specific_product_assertion():
    action = "这款粉底适合敏感肤质。"
    assert validate([candidate(
        action=action,
        claims=[{"text": action, "source_refs": ["k1"]}],
    )])


def test_claims_must_match_the_action_not_a_new_fact():
    assert validate([candidate(
        claims=[{"text": "每天使用两次", "source_refs": ["k1"]}],
    )])


@pytest.mark.parametrize("body, rejected", [
    ("这次不再重复让您先保湿。干燥区域仍要保留适度保湿。", True),
    ("理解您已经试过加强保湿。这次不再要求保湿。", False),
    ("我不会再建议先保湿。您已经试过加强保湿，当前只比较妆效。", False),
    ("加强保湿已经试过，这次不会再建议先保湿。", False),
    ("不再建议清洁保湿，关注是否标注oil-free。", False),
    ("不再建议清洁保湿，但干燥区域仍要保留适度保湿。", True),
])
def test_declined_care_is_not_reintroduced_in_another_clause(body, rejected):
    assert bool(validate_care_preferences(
        [body], "已经试过保湿，不要再清洁保湿，只核对筛选条件。",
    )) is rejected
