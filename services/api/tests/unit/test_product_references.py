import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.domain.consumer_service.grounding import validate_claims
from app.knowledge.document_metadata import DocumentMetadata, publication_content
from app.knowledge.models import (
    Base,
    KnowledgeBaseRow,
    KnowledgeDocumentMetadataRow,
    KnowledgeDraftRow,
)
from app.knowledge.reference_products import BASE_ID, seed_reference_products
from app.schemas.grounding import GroundingClaim, GroundingSource


def test_product_metadata_requires_identity_and_source():
    with pytest.raises(ValidationError):
        DocumentMetadata(scope="product_specific", product_sku="REF-1")
    with pytest.raises(ValidationError):
        DocumentMetadata(scope="product_specific", source_label="官网")
    value = DocumentMetadata(
        scope="product_specific", product_sku="REF-US-PROMATTE",
        product_name="Infallible Pro-Matte 粉底液", market="US",
        provenance="official_reference", source_label="品牌官网",
        source_url="https://example.com/product",
    )
    assert value.market == "US"


def test_public_references_are_seeded_as_separate_knowledge_documents(tmp_path):
    engine = build_engine(Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'refs.sqlite3'}"))
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as session:
        seed_reference_products(session)
        session.commit()
        base = session.get(KnowledgeBaseRow, BASE_ID)
        drafts = list(session.scalars(select(KnowledgeDraftRow).where(
            KnowledgeDraftRow.knowledge_base_id == BASE_ID,
        )))
        assert base is not None and base.source_type == "product_knowledge"
        assert len(drafts) == 7
        cn = next(item for item in drafts if "lrlwx26040" in item.document_id)
        assert "黑胖子气垫" in cn.content
        metadata = session.get(
            KnowledgeDocumentMetadataRow, (cn.document_id, "draft"),
        )
        assert metadata is not None and '"product_sku":"LRLWX26040"' in metadata.payload_json
        lotion = session.get(KnowledgeDraftRow, "loreal-reference-lrlwx26013")
        assert "精华水130ml和精华乳110ml" in lotion.content
        assert "不等于零残留、无香精、敏感肌适用或过敏安全" in lotion.content
        cream = session.get(KnowledgeDraftRow, "loreal-reference-lrlwx26008")
        assert "不能移用到此套装中的面霜" in cream.content
        assert "不是单瓶面霜货号" in cream.content
        lotion.content, lotion.revision = "客服手动编辑的已确认资料", 5
        session.commit()
        seed_reference_products(session)
        session.flush()
        assert lotion.content == "客服手动编辑的已确认资料" and lotion.revision == 5


def test_publication_header_preserves_market_and_provenance():
    metadata = DocumentMetadata(
        scope="product_specific", product_sku="REF-US-PROGLOW",
        product_name="Infallible Pro-Glow 粉底液", market="US",
        provenance="official_reference", source_label="美国官网",
        source_url="https://example.com/product",
    )
    text = publication_content("商品资料", "官网描述的妆效仍需结合个人情况核对。", metadata)
    assert "商品专属资料，关联商品标识：REF-US-PROGLOW" in text
    assert "参考市场：美国" in text
    assert "官方公开参考资料" in text


def test_brand_attributes_require_correct_product_and_market_citations():
    a = GroundingSource(
        source_id="a", kind="knowledge", subject_id="a", label="美国官网商品",
        text="Infallible Pro-Matte 粉底液：半哑光、中等遮盖。",
        fields={"scope": "product_specific", "productSku": "REF-US-PROMATTE",
                "productName": "Infallible Pro-Matte 粉底液", "products": ["REF-US-PROMATTE"],
                "productAliases": ["Infallible Pro-Matte", "Pro-Matte"],
                "provenance": "official_reference", "market": "US"},
    )
    b = a.model_copy(update={"source_id": "b", "text": "Infallible Pro-Glow 粉底液：自然光泽、中等遮盖。", "fields": {
        **a.fields, "productSku": "REF-US-PROGLOW", "productName": "Infallible Pro-Glow 粉底液",
        "products": ["REF-US-PROGLOW"], "productAliases": ["Infallible Pro-Glow", "Pro-Glow"],
    }})
    catalog = {"a": a, "b": b}
    body = "按美国官网说明，Infallible Pro-Matte 粉底液为半哑光。"
    assert not validate_claims(body, [GroundingClaim(text=body, source_refs=["a"])], catalog)
    assert validate_claims(body, [], catalog)
    assert validate_claims(body, [GroundingClaim(text=body, source_refs=["b"])], catalog)
    unqualified = "Infallible Pro-Matte 粉底液为半哑光。"
    assert validate_claims(
        unqualified, [GroundingClaim(text=unqualified, source_refs=["a"])], catalog,
    )
    mixed = "美国官网：Infallible Pro-Matte 粉底液和Infallible Pro-Glow 粉底液均为半哑光。"
    assert validate_claims(mixed, [GroundingClaim(text=mixed, source_refs=["a"])], catalog)
    assert not validate_claims(
        body, [GroundingClaim(text="半哑光", source_refs=["a"])], catalog,
    )
    disclaimer = "按美国官网，本次资料不能保证个人适用性。"
    assert not validate_claims(
        disclaimer, [GroundingClaim(text=disclaimer, source_refs=["a", "b"])], catalog,
    )
    positive_after_negative = "按美国官网，不能保证个人适用性，但它具有水润质地。"
    assert validate_claims(
        positive_after_negative, [GroundingClaim(text=positive_after_negative, source_refs=["a"])],
        catalog,
    )
    natural = "按美国官网资料，Pro-Matte 是半哑光。Pro-Glow 的妆效偏自然光泽。"
    assert not validate_claims(natural, [
        GroundingClaim(text="Pro-Matte 是半哑光", source_refs=["a"]),
        GroundingClaim(text="Pro-Glow 的妆效偏自然光泽", source_refs=["b"]),
    ], catalog)
    assert validate_claims(natural, [
        GroundingClaim(text="Pro-Matte 是半哑光", source_refs=["b"]),
        GroundingClaim(text="Pro-Glow 的妆效偏自然光泽", source_refs=["a"]),
    ], catalog)
    comparison = "按美国官网，Pro-Matte 是半哑光，而Pro-Glow 的妆效偏自然光泽。"
    assert not validate_claims(comparison, [
        GroundingClaim(text="Pro-Matte 是半哑光", source_refs=["a"]),
        GroundingClaim(text="Pro-Glow 的妆效偏自然光泽", source_refs=["b"]),
    ], catalog)
    from app.domain.consumer_service.personalization import AdviceCandidate, validate_advice

    customer = GroundingSource(
        source_id="m1", kind="customer_message", subject_id="c1", label="消费者自述",
        text="更在意半哑光和中等遮盖。",
    )
    action = "按美国官网，Pro-Matte 是半哑光，比Pro-Glow 的自然光泽更接近您的偏好。"
    candidate = AdviceCandidate(
        category="product_selection", title="按妆效选候选",
        action=action, rationale="依据半哑光偏好比较，不保证个人适用。",
        scope="product_specific", product_sku="REF-US-PROMATTE",
        evidence=[
            {"source_ref": "m1", "quote": customer.text},
            {"source_ref": "a", "quote": "半哑光、中等遮盖"},
            {"source_ref": "b", "quote": "自然光泽、中等遮盖"},
        ],
        claims=[
            GroundingClaim(text="Pro-Matte 是半哑光", source_refs=["a"]),
            GroundingClaim(text="Pro-Glow 的自然光泽", source_refs=["b"]),
        ],
    )
    assert not validate_advice(
        [candidate], {**catalog, "m1": customer}, intent="product_question",
        handoff_required=False, latest_message=customer.text,
    )


def test_shared_cn_personal_suitability_disclaimer_is_not_a_mixed_product_attribute():
    def source(key, name):
        return GroundingSource(
            source_id=key, kind="knowledge", subject_id=key, label="中国官网商品资料",
            text=f"{name}：品牌资料不能保证个人适用。当前未提供完整成分表。",
            fields={"scope": "product_specific", "productSku": key, "productName": name,
                    "products": [key], "provenance": "official_reference", "market": "CN"},
        )
    catalog = {
        "a": source("a", "4.0小蜜罐水乳套装"),
        "b": source("b", "4.0小蜜罐轻盈版水霜套装"),
    }
    body = ("4.0小蜜罐水乳套装与4.0小蜜罐轻盈版水霜套装都不构成个人适用保证，"
            "也不要求您额外叠加一层霜；您可按官网规格自行取舍。")
    claim = GroundingClaim(text=body, source_refs=["a", "b"])
    assert not validate_claims(body, [claim], catalog)
    asserted = body + "但两款的配方都适用所有肤质。"
    assert validate_claims(
        asserted, [GroundingClaim(text=asserted, source_refs=["a", "b"])], catalog,
    )
    unquoted = body + "4.0小蜜罐轻盈版水霜套装为水润质地。"
    assert validate_claims(unquoted, [claim], catalog)


def test_delimited_product_comparison_binds_each_attribute_to_its_own_source():
    def source(key, name, attribute):
        return GroundingSource(
            source_id=key, kind="knowledge", subject_id=key, label="中国官网商品资料",
            text=f"{name}：{attribute}。",
            fields={"scope": "product_specific", "productSku": key, "productName": name,
                    "products": [key], "provenance": "official_reference", "market": "CN"},
        )
    catalog = {
        "a": source("a", "4.0小蜜罐水乳", "官网介绍轻盈质地"),
        "b": source("b", "4.0小蜜罐轻盈版水霜", "精华水与面霜的规格"),
        "c": source("c", "另一款护肤乳", "水润质地"),
    }
    body = ("按官网对4.0小蜜罐水乳轻盈质地的定位，它更接近白天的轻薄偏好；"
            "4.0小蜜罐轻盈版水霜为精华水与面霜的规格，不能保证本人适用。")
    assert not validate_claims(
        body, [GroundingClaim(text=body, source_refs=["a", "b"])], catalog,
    )
    assert validate_claims(
        body, [GroundingClaim(text=body, source_refs=["a"])], catalog,
    )
    assert validate_claims(
        body, [GroundingClaim(text=body, source_refs=["b"])], catalog,
    )
    mixed = "4.0小蜜罐水乳和4.0小蜜罐轻盈版水霜都具有轻盈质地。"
    assert validate_claims(
        mixed, [GroundingClaim(text=mixed, source_refs=["a", "b"])], catalog,
    )
    foreign = body + "另一款护肤乳为水润质地。"
    assert validate_claims(
        foreign, [GroundingClaim(text=foreign, source_refs=["a", "b"])], catalog,
    )
    uncertain_then_positive = (
        "4.0小蜜罐水乳和4.0小蜜罐轻盈版水霜不保证本人适用，"
        "但两款的配方都适用所有肤质。"
    )
    assert validate_claims(
        uncertain_then_positive,
        [GroundingClaim(text=uncertain_then_positive, source_refs=["a", "b"])], catalog,
    )
