from types import SimpleNamespace

import pytest

from app.config import Settings
from app.domain.enums import Visibility
from app.integrations.embedding_provider import MockEmbeddingProvider
from app.knowledge import retrieval
from app.knowledge.document_metadata import DocumentMetadata


@pytest.mark.parametrize("rerank", [False, True])
def test_selected_full_source_keeps_tail_conditions_without_expanding_ui_excerpt(monkeypatch, rerank):
    text = "资料开头。" * 100 + "末尾条件：这是部分成分信息，不保证敏感肌适用。"
    payload = {
        "document_id": "cn-lotion", "document_version": "1", "document_title": "中国商品资料",
        "knowledge_base_id": "loreal-test", "visibility": "internal",
        "product_models": ["global"], "regions": ["CN"], "channels": ["general"],
    }
    hits = [
        SimpleNamespace(chunk_id=f"cn-lotion@1#{i}", score=0.5,
                        payload={**payload, "text": value, "content_hash": str(i)})
        for i, value in enumerate([text, "另一个没有入选的片段"])
    ]
    snapshot = SimpleNamespace(
        snapshot_id="fixture-snapshot", qdrant_collection="fixture-index", vector_dimension=8,
    )

    class Store:
        def __init__(self, *args, **kwargs):
            pass

        def hybrid_search(self, *args, **kwargs):
            return hits

        def channel_ranks(self, *args, **kwargs):
            return {}

        def close(self):
            pass

    monkeypatch.setattr(retrieval, "QdrantKnowledgeStore", Store)
    monkeypatch.setattr(retrieval, "KnowledgeRepository", lambda _: SimpleNamespace(
        get_active_snapshot=lambda: snapshot,
    ))
    monkeypatch.setattr(retrieval, "read_metadata", lambda *args: DocumentMetadata())
    reranker = SimpleNamespace(
        available=lambda: True, model_id="explicit-rerank-fixture",
        rerank=lambda query, texts, top_n: [SimpleNamespace(index=1, score=0.8)],
    ) if rerank else None
    result = retrieval.retrieve(
        None, settings=Settings(run_mode="mock", retrieval_max_evidence=1),
        embedding_provider=MockEmbeddingProvider(reason="explicit-retrieval-fixture"),
        request=retrieval.RetrievalRequest(query="核对商品限制", audience=Visibility.INTERNAL,
                                           country_code="CN"),
        rerank_provider=reranker,
    )
    selected_index = 1 if rerank else 0
    selected_id = f"cn-lotion@1#{selected_index}"
    assert result.evidence[0].chunk_id == selected_id
    assert result.source_texts == {selected_id: hits[selected_index].payload["text"]}
    if not rerank:
        assert len(result.evidence[0].quoted_excerpt) == 400
        assert "末尾条件" not in result.evidence[0].quoted_excerpt
    assert "source_text" not in result.evidence[0].model_dump()
