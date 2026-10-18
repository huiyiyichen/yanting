"""演示商品补充资料（反馈 10-18 #1）。

失败方式：
F1 孕期成分问题检索不到商品专属资料，回复只能“暂时没查到资料，请拍成分表”；
F2 命中的资料没有绑定货号 XL21205，商品专属事实无法通过归属校验；
F3 资料里缺少“不含维A酸/水杨酸/二苯酮类”或“建议咨询产检医生”，回复缺依据。
"""
from dataclasses import replace

from tests.integration import test_reception_workspace as fixtures

from app.integrations.embedding_provider import MockEmbeddingProvider
from app.knowledge.reference_products import seed_reference_products

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT
QUESTION = (
    "你好，请问测试温和氨基酸洁面乳120ml孕妇能用吗？我怀孕三个月了，之前一直在用，现在有点不敢用了 "
    "麻烦帮我看下成分有没孕妇不能用的，维A酸水杨酸那些"
)


def test_pregnancy_ingredient_question_hits_product_specific_material(workspace, tmp_path):
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

    data = client.post("/api/platform/knowledge/search", headers=SUPPORT,
                       json={"query": QUESTION}).json()
    hits = [e for e in data["evidence"] if e["document_id"] == "loreal-fictional-xl21205"]
    assert hits, [e["document_id"] for e in data["evidence"]]
    assert hits[0]["document_metadata"]["productSku"] == "XL21205"
    assert hits[0]["applicability"]["products"] == ["XL21205"]
    text = "".join(data["sourceTexts"][e["chunk_id"]] for e in hits)
    for phrase in ("维A酸", "水杨酸", "二苯酮", "产检医生"):
        assert phrase in text, phrase
