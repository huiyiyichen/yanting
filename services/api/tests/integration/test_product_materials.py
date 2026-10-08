"""Metadata/index lifecycle uses an explicit index fixture, not live-model accuracy."""

from dataclasses import replace

from sqlalchemy import select
from tests.integration import test_reception_workspace as fixtures

from app.domain.consumer_service.models import SourceRecordRow
from app.integrations.embedding_provider import MockEmbeddingProvider
from app.knowledge.document_metadata import read_metadata
from app.knowledge.models import KnowledgeDocumentRow
from app.knowledge.reference_products import seed_reference_products

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def test_real_reference_catalog_binding_and_published_metadata_are_independent(workspace, tmp_path):
    client, factory, _ = workspace
    with factory() as session:
        before = {row.record_id: row.row_sha256 for row in session.scalars(select(SourceRecordRow))}
        seed_reference_products(session)
        session.commit()
    catalog = client.get("/api/platform/knowledge/products", headers=SUPPORT)
    assert catalog.status_code == 200, catalog.text
    rows = catalog.json()
    assert len(rows) == 27
    assert sum(row["identityKind"] == "official_fixture" for row in rows) == 20
    assert sum(row["identityKind"] == "brand_reference" for row in rows) == 7
    assert client.get("/api/platform/knowledge/products", headers=CUSTOMER).status_code == 403
    document_id = "loreal-reference-lrlwx26040"
    path = f"/api/platform/knowledge/documents/{document_id}"
    draft = client.get(path, headers=SUPPORT).json()
    assert draft["metadata"]["productSku"] == "LRLWX26040"
    assert draft["metadata"]["market"] == "CN"
    assert "商品专属资料" in draft["chunks"][0]["text"]

    class IndexFixture(MockEmbeddingProvider):
        def encode(self, texts, *, is_query=False):
            return replace(super().encode(texts, is_query=is_query), is_mock=False)

    runtime = client.app.state.runtime
    runtime.settings.runtime_dir = str(tmp_path / "runtime")
    runtime.settings.qdrant_path = str(tmp_path / "qdrant")
    runtime.embedding_provider = IndexFixture(reason="explicit-index-fixture")
    publication = client.post("/api/platform/knowledge/publish", headers=SUPPORT)
    assert publication.status_code == 200 and publication.json()["ok"], publication.text
    with factory() as session:
        lotion = read_metadata(session, "loreal-reference-lrlwx26013", "edit-1")
        assert lotion.product_sku == "LRLWX26013" and lotion.market == "CN"
        assert lotion.product_aliases == ["4.0小蜜罐水乳", "小蜜罐水乳4.0"]
        published = read_metadata(session, document_id, "edit-1")
        assert published.product_sku == "LRLWX26040"
        row = session.scalar(select(KnowledgeDocumentRow).where(
            KnowledgeDocumentRow.document_id == document_id,
        ))
        assert row.product_models_json == '["LRLWX26040"]'
    body = {
        "title": draft["title"], "knowledgeBaseId": draft["knowledgeBaseId"],
        "content": draft["content"], "expectedRevision": 1,
        "metadata": {**draft["metadata"], "sourceLabel": "新的待发布登记"},
    }
    updated = client.put(path, headers=SUPPORT, json=body)
    assert updated.status_code == 200, updated.text
    with factory() as session:
        assert read_metadata(session, document_id, "edit-1").source_label == published.source_label
        assert read_metadata(session, document_id, "draft").source_label == "新的待发布登记"
        assert {row.record_id: row.row_sha256 for row in session.scalars(select(SourceRecordRow))} == before
    assert client.put(path, headers=SUPPORT, json=body).status_code == 409
    bad = {**body, "expectedRevision": 2, "metadata": {**body["metadata"], "productSku": "missing"}}
    assert client.put(path, headers=SUPPORT, json=bad).status_code == 422
