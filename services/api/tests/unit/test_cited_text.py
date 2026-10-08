import pytest
from pydantic import ValidationError

from app.domain.consumer_service.grounded_workflow import GroundedReply
from app.domain.consumer_service.grounding import validate_claims
from app.domain.consumer_service.personalization import AdviceCandidate
from app.schemas.grounding import GroundingSource


def test_parts_render_exactly_and_do_not_invent_missing_references():
    reply = GroundedReply.model_validate({
        "style": "recommended", "segments": [
            {"text": "我先按这笔订单核对。", "source_refs": []},
            {"text": "订单111111实付10元。", "source_refs": ["o1"]},
        ],
    })
    source = GroundingSource(
        source_id="o1", kind="order", subject_id="111111", label="订单",
        text="订单111111实付10元", fields={"orderId": "111111", "paidAmount": "10"},
    )
    assert reply.body == "我先按这笔订单核对。订单111111实付10元。"
    assert reply.claims[0].text == "订单111111实付10元。"
    assert not validate_claims(reply.body, reply.claims, {"o1": source})
    assert validate_claims(reply.body, reply.claims, {})
    uncited = GroundedReply.model_validate({
        "style": "recommended", "segments": [{"text": "订单111111实付10元。"}],
    })
    assert uncited.claims == []
    assert validate_claims(uncited.body, uncited.claims, {"o1": source})
    assert "segments" not in reply.model_dump()


def test_advice_parts_keep_individual_field_citations_and_legacy_format():
    candidate = AdviceCandidate.model_validate({
        "category": "routine", "title": "按当前情况选择",
        "action_parts": [{"text": "先核对通用标签。", "source_refs": ["k1"]}],
        "rationale_parts": [{"text": "你明确在意使用感受。", "source_refs": ["m1"]}],
        "evidence": [
            {"source_ref": "k1", "quote": "核对标签"},
            {"source_ref": "m1", "quote": "在意使用感受"},
        ],
    })
    assert candidate.action == "先核对通用标签。"
    assert candidate.rationale == "你明确在意使用感受。"
    assert [claim.text for claim in candidate.claims] == [candidate.action, candidate.rationale]
    assert AdviceCandidate.model_validate(candidate.model_dump()) == candidate
    assert GroundedReply.model_validate({"style": "recommended", "body": "我先核对。"}).body == "我先核对。"


def test_segments_do_not_silently_replace_conflicting_bodies_or_extra_fields():
    for value in [
        {"style": "recommended", "body": "不能被忽略的另一段正文", "segments": [{"text": "安全话语"}]},
        {"style": "recommended", "segments": [{"text": "安全话语", "unknown": "另一段内容"}]},
        {"style": "recommended", "segments": []},
    ]:
        with pytest.raises(ValidationError):
            GroundedReply.model_validate(value)
