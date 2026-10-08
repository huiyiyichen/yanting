from app.domain.consumer_service.personalization import (
    AdviceCandidate,
    advice_views,
    validate_advice,
)
from app.schemas.consumer_service import PersonalizedAdviceView
from app.schemas.grounding import GroundingSource


def catalog():
    return {
        "m1": GroundingSource(
            source_id="m1", kind="customer_message", subject_id="c1", label="消费者自述",
            text="我更在意半哑光。",
        ),
        "matte": GroundingSource(
            source_id="matte", kind="knowledge", subject_id="matte", label="美国Matte资料",
            text="Pro-Matte 为半哑光。",
            fields={"scope": "product_specific", "productSku": "REF-MATTE",
                    "productName": "Pro-Matte", "products": ["REF-MATTE"], "market": "US"},
        ),
        "glow": GroundingSource(
            source_id="glow", kind="knowledge", subject_id="glow", label="美国Glow资料",
            text="资料来源：品牌官网 来源网址：https://example.test/glow"
                 "美国官网介绍Pro-Glow为自然光泽。只是品牌定位，不保证个人适用。",
            fields={"scope": "product_specific", "productSku": "REF-GLOW",
                    "productName": "Pro-Glow", "products": ["REF-GLOW"], "market": "US",
                    "sourceUrl": "https://example.test/glow"},
        ),
        "unused": GroundingSource(
            source_id="unused", kind="knowledge", subject_id="unused", label="未引用知识",
            text="未被模型引用的资料，不应自动加入。",
        ),
    }


def candidate(with_claims=True):
    return AdviceCandidate(
        category="product_selection", title="比较妆效", scope="product_specific",
        product_sku="REF-MATTE",
        action="按美国官网，Pro-Matte 为半哑光；Pro-Glow 为自然光泽。",
        rationale="对应半哑光的偏好。",
        evidence=[{"source_ref": "m1", "quote": "我更在意半哑光"},
                  {"source_ref": "matte", "quote": "Pro-Matte 为半哑光"}],
        claims=[
            {"text": "Pro-Matte 为半哑光", "source_refs": ["matte"]},
            {"text": "Pro-Glow 为自然光泽", "source_refs": ["glow"]},
            {"text": "对应半哑光的偏好", "source_refs": ["m1"]},
        ] if with_claims else [],
    )


def test_checked_comparison_shows_both_used_sources_and_exact_whole_qualification():
    item, sources = candidate(), catalog()
    assert validate_advice(
        [item], sources, intent="product_question", handoff_required=False,
        latest_message="我更在意半哑光。",
    ) == []
    result = advice_views([item], sources)[0]
    assert result.product_name == "Pro-Matte"
    assert [e.source_ref for e in result.evidence] == ["m1", "matte", "glow"]
    assert result.evidence[-1].quote == "美国官网介绍Pro-Glow为自然光泽。只是品牌定位，不保证个人适用。"
    assert result.evidence[-1].quote in sources["glow"].text
    assert "来源网址" not in result.evidence[-1].quote
    assert result.claims == item.claims
    assert len(item.evidence) == 2
    assert advice_views([item], sources)[0] == result


def test_uncited_catalog_items_are_not_guessed_into_the_card():
    result = advice_views([candidate(with_claims=False)], catalog())[0]
    assert [e.source_ref for e in result.evidence] == ["m1", "matte"]
    assert result.claims == []


def test_missing_source_locator_keeps_original_text_and_old_cache_has_no_fabricated_claims():
    sources = catalog()
    sources["glow"].fields.pop("sourceUrl")
    result = advice_views([candidate()], sources)[0]
    assert result.evidence[-1].quote == sources["glow"].text
    legacy = PersonalizedAdviceView.model_validate({
        "category": "routine", "title": "旧建议", "action": "核对资料",
        "rationale": "当前诉求", "evidence": [],
    })
    assert legacy.claims == [] and legacy.evidence == []
