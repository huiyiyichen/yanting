from datetime import UTC, datetime

import pytest

from app.domain.case_state.models import AttachmentRow
from app.domain.consumer_service.grounding import validate_claims, validate_memory
from app.domain.consumer_service.image_evidence import (
    ImageObservation,
    observation_source,
    validate_image_claim,
)
from app.schemas.grounding import GroundingClaim, GroundingSource, MemoryItem


def picture():
    return GroundingSource(
        source_id="image:a1", kind="image_observation", subject_id="c1", label="图片",
        text="图中文字：已签收\n图中文字：实付98元\n图中文字：2604B",
        fields={"visibleText": ["已签收", "实付98元", "2604B"], "analyzed": True},
    )


@pytest.mark.parametrize("text,accepted", [
    ("截图显示已签收。", True),
    ("图中显示实付98元。", True),
    ("照片上的字符是2604B。", True),
    ("亲，照片里的批次号是2604B。", True),
    ("包裹已签收。", False),
    ("您的订单实付98元。", False),
    ("截图显示已签收。您的包裹已经签收了。", False),
    ("图片上的批次号2604B说明肯定是正品。", False),
])
def test_picture_is_attributed_not_a_business_status(text, accepted):
    source = picture()
    claim = GroundingClaim(text=text, source_refs=[source.source_id])
    assert bool(validate_claims(text, [claim], {source.source_id: source})) is not accepted


def test_image_observation_cannot_be_saved_as_a_customer_statement():
    source = picture()
    assert validate_memory([
        MemoryItem(category="known", source_ref=source.source_id, quote="2604B"),
    ], {source.source_id: source})


def test_cited_image_fragment_uses_actual_same_sentence_attribution_not_another_sentence():
    source = picture()
    claim = GroundingClaim(text="2604B", source_refs=[source.source_id])
    assert not validate_claims("照片里的批次号是2604B。", [claim], {source.source_id: source})
    assert validate_claims("我看了照片。批次号是2604B。", [claim], {source.source_id: source})


def test_product_identity_is_a_short_qualified_image_claim():
    attachment = AttachmentRow(
        attachment_id="a-product",
        conversation_id="c1",
        message_id="m1",
        mime_type="image/png",
        byte_size=10,
        stored_path="runtime/a-product.png",
        sha256="a" * 64,
        created_at=datetime.now(UTC),
    )
    observation = ImageObservation(
        attachment_id="a-product",
        category="product_identity",
        readable=True,
        visible_text=["巴黎欧莱雅"],
        visible_clues=["金色水乳套装包装"],
        uncertainties=[],
        identified_products=[{
            "product_sku": "LRLWX26013",
            "product_name": "欧莱雅金致小蜜罐4.0水乳套装",
            "confidence": "high",
        }],
        requires_human_review=False,
    )
    source = observation_source(attachment, observation)
    body = "亲，照片上看起来是欧莱雅金致小蜜罐4.0水乳套装。"
    claim = GroundingClaim(text=body, source_refs=[source.source_id])
    assert validate_image_claim(body, [source], body=body) == []
    assert validate_claims(body, [claim], {source.source_id: source}) == []
