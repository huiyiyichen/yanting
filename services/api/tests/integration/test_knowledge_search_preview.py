"""知识检索预览（P2-3）。

失败方式：
F1 检索测试只给截断摘录，运营看不到片段全文，无法判断命中是否真的相关；
F2 全文按 chunk 对不上（错配或缺失），预览显示了别的片段；
F3 全文泄露给客户角色（检索测试是内部工具，客户不得调用）。
"""
from dataclasses import replace

from tests.integration import test_reception_workspace as fixtures

from app.integrations.embedding_provider import MockEmbeddingProvider
from app.knowledge.reference_products import seed_reference_products

workspace = fixtures.workspace


def squash(text: str) -> str:
    """摘录会压缩空白，比较前统一去掉。"""
    return "".join(text.split())
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def test_search_returns_full_chunk_text_per_evidence(workspace, tmp_path):
    client, factory, _ = workspace
    with factory() as session:
        seed_reference_products(session)
        session.commit()

    class IndexFixture(MockEmbeddingProvider):
        def encode(self, texts, *, is_query=False):
            return replace(super().encode(texts, is_query=is_query), is_mock=False)

    runtime = client.app.state.runtime
    runtime.settings.runtime_dir = str(tmp_path / "runtime")
    runtime.settings.qdrant_path = str(tmp_path / "qdrant")
    runtime.embedding_provider = IndexFixture(reason="explicit-index-fixture")
    assert client.post("/api/platform/knowledge/publish", headers=SUPPORT).json()["ok"]

    body = {"query": "小蜜罐水乳怎么用"}
    result = client.post("/api/platform/knowledge/search", headers=SUPPORT, json=body)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["evidence"], data
    texts = data["sourceTexts"]
    for item in data["evidence"]:
        full = texts[item["chunk_id"]]
        assert len(full) >= len(item["quoted_excerpt"].rstrip("…"))
        assert squash(item["quoted_excerpt"].rstrip("…"))[:20] in squash(full)
    assert set(texts) == {item["chunk_id"] for item in data["evidence"]}
    assert client.post("/api/platform/knowledge/search", headers=CUSTOMER, json=body).status_code == 403
