"""诊断：dense 与 sparse 两路的排名分歧程度。

为什么需要它：模式对照显示三种模式 Hit@5 完全相同，说明当前评测集无法区分两路。
本脚本量化「两路是否真的有分歧」，从而判断这是
(a) 评测集饱和（任务对其余两路都太容易），还是
(b) 稀疏通道实际上没有贡献（实现缺陷）。

做法：对同一问题，分别取两路的召回排名，统计它们的前 5 名重合度。

用法：python scripts/probe_lane_divergence.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from qdrant_client import models  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import build_engine, build_session_factory  # noqa: E402
from app.domain.enums import Visibility  # noqa: E402
from app.integrations.embedding_provider import build_embedding_provider  # noqa: E402
from app.integrations.qdrant_store import QdrantKnowledgeStore  # noqa: E402
from app.knowledge.repository import KnowledgeRepository  # noqa: E402
from app.knowledge.retrieval import RetrievalRequest, build_filter  # noqa: E402

CASES = REPO / "evals" / "cases"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="calibration")
    args = parser.parse_args()

    payload = json.loads((CASES / f"{args.split}.json").read_text(encoding="utf-8"))
    cases = [item for item in payload["cases"] if item.get("answerable", True)]

    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    provider = build_embedding_provider(settings)
    session = factory()
    store = None
    rows: list[dict] = []
    try:
        repository = KnowledgeRepository(session)
        snapshot = repository.get_active_snapshot()
        if snapshot is None:
            print("没有有效快照")
            return 2
        store = QdrantKnowledgeStore(
            settings.qdrant_path_resolved, vector_dimension=snapshot.vector_dimension
        )

        for case in cases:
            request = RetrievalRequest(
                query=case["question"],
                audience=(
                    Visibility.INTERNAL
                    if case.get("audience") == "internal"
                    else Visibility.CUSTOMER_VISIBLE
                ),
                product_model=case.get("product_model"),
                country_code=case.get("country_code"),
            )
            query_filter, _ = build_filter(request)
            batch = provider.encode([case["question"]], is_query=True)
            dense = batch.dense[0]
            sparse = batch.sparse[0]

            # 必须与生产链路的单路召回深度一致（top_k=8），
            # 否则这里量到的分歧度与线上实际行为不符（曾用 5 导致误判）。
            lane_k = settings.retrieval_top_k
            dense_points = store._ensure_client().query_points(
                collection_name=snapshot.qdrant_collection,
                query=dense,
                using="dense",
                limit=lane_k,
                query_filter=query_filter,
                with_payload=True,
            ).points
            sparse_points = store._ensure_client().query_points(
                collection_name=snapshot.qdrant_collection,
                query=models.SparseVector(indices=sparse.indices, values=sparse.values),
                using="sparse",
                limit=lane_k,
                query_filter=query_filter,
                with_payload=True,
            ).points

            dense_docs = [str((p.payload or {}).get("document_id")) for p in dense_points]
            sparse_docs = [str((p.payload or {}).get("document_id")) for p in sparse_points]
            dense_ids = [str((p.payload or {}).get("chunk_id")) for p in dense_points]
            sparse_ids = [str((p.payload or {}).get("chunk_id")) for p in sparse_points]
            overlap = len(set(dense_ids) & set(sparse_ids))
            expected = set(case.get("expected_document_ids") or [])
            rows.append(
                {
                    "case_id": case["case_id"],
                    "lane_k": lane_k,
                    "chunk_overlap_at_k": overlap,
                    "dense_top1_in_expected": bool(expected & set(dense_docs[:1])),
                    "sparse_top1_in_expected": bool(expected & set(sparse_docs[:1])),
                    "dense_hits_expected": bool(expected & set(dense_docs)),
                    "sparse_hits_expected": bool(expected & set(sparse_docs)),
                    "dense_top1": dense_docs[0] if dense_docs else None,
                    "sparse_top1": sparse_docs[0] if sparse_docs else None,
                }
            )
    finally:
        if store is not None:
            store.close()
        session.close()
        engine.dispose()

    identical = sum(1 for r in rows if r["chunk_overlap_at_k"] == r["lane_k"])
    zero_overlap = sum(1 for r in rows if r["chunk_overlap_at_k"] == 0)
    dense_only_hits = sum(
        1 for r in rows if r["dense_hits_expected"] and not r["sparse_hits_expected"]
    )
    sparse_only_hits = sum(
        1 for r in rows if r["sparse_hits_expected"] and not r["dense_hits_expected"]
    )
    neither = sum(
        1 for r in rows if not r["dense_hits_expected"] and not r["sparse_hits_expected"]
    )
    report = {
        "split": args.split,
        "cases": len(rows),
        "lane_k": rows[0]["lane_k"] if rows else None,
        "chunk_overlap_identical_both_lanes": identical,
        "chunk_overlap_zero": zero_overlap,
        "mean_chunk_overlap_at_k": round(
            sum(r["chunk_overlap_at_k"] for r in rows) / len(rows), 2
        ),
        "cases_only_dense_has_expected": dense_only_hits,
        "cases_only_sparse_has_expected": sparse_only_hits,
        "cases_neither_lane_has_expected": neither,
        "rows": rows,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    out = REPO / "evals" / "results" / f"lane-divergence-{args.split}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
