"""检索评测：Hit@5、过滤越界、停用文档排除。

指标定义（PRD AC-27）：
    Hit@5 = 前五条至少包含一条标注相关证据的**可回答问题数** / 可回答问题数

补充必须同时报告的指标：
- 负例（不可回答）问题不得返回"看起来正确"的证据；
- 过滤越界次数必须为 0（客户视角不得返回 internal；CN 查询不得返回 US 专属政策）；
- 停用文档不得出现在任何结果中。

通过率一律给出分子/分母；跳过与未运行不计入通过。

用法：
    python scripts/run_retrieval_eval.py --split calibration
    python scripts/run_retrieval_eval.py --split holdout --chunk-size 400 --chunk-overlap 60
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.config import Settings  # noqa: E402
from app.db import build_engine, build_session_factory  # noqa: E402
from app.domain.enums import Visibility  # noqa: E402
from app.integrations.embedding_provider import build_embedding_provider  # noqa: E402
from app.knowledge.retrieval import RetrievalRequest, retrieve  # noqa: E402

CASES_ROOT = REPO / "evals" / "cases"
RESULTS_ROOT = REPO / "evals" / "results"

# 客户可见的专属文档按地区划分；用于越界检查
REGION_SCOPED_DOCS = {
    "doc-warranty-consumer-cn": "CN",
    "doc-warranty-consumer-us": "US",
    "doc-product-s1pro-robot-cn": "CN",
}
DISABLED_DOCS = {"doc-ts-stick-no-suction-legacy"}


@dataclass
class CaseOutcome:
    case_id: str
    question: str
    answerable: bool
    hit_at_5: bool | None
    returned_document_ids: list[str] = field(default_factory=list)
    returned_chunk_count: int = 0
    top_rrf: float | None = None
    hit_status: str = ""
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def load_cases(split: str) -> dict:
    path = CASES_ROOT / f"{split}.json"
    if not path.exists():
        raise SystemExit(f"评测集不存在：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_split(
    split: str,
    *,
    settings: Settings,
    snapshot_id: str | None = None,
    mode: str = "hybrid",
) -> dict:
    payload = load_cases(split)
    cases = payload["cases"]

    engine = build_engine(settings)
    factory = build_session_factory(engine)
    provider = build_embedding_provider(settings)
    # 精排必须与线上同源：按当前 Settings 构建；未配置时为 None（如实按"没有重排序"跑）
    from app.integrations.rerank_provider import build_rerank_provider

    rerank_provider = build_rerank_provider(settings)
    if rerank_provider is not None:
        print(f"重排序已启用：{rerank_provider.model_id}（候选数 {settings.rerank_candidates}）")
    else:
        print("重排序未启用：按召回顺序返回")
    session = factory()

    outcomes: list[CaseOutcome] = []
    latencies: list[float] = []
    try:
        for case in cases:
            audience = (
                Visibility.INTERNAL
                if case.get("audience") == "internal"
                else Visibility.CUSTOMER_VISIBLE
            )
            started = time.perf_counter()
            result = retrieve(
                session,
                settings=settings,
                embedding_provider=provider,
                rerank_provider=rerank_provider,
                request=RetrievalRequest(
                    query=case["question"],
                    audience=audience,
                    product_model=case.get("product_model"),
                    country_code=case.get("country_code"),
                    purchase_channel=case.get("purchase_channel"),
                    snapshot_id=snapshot_id,
                    mode=mode,  # type: ignore[arg-type]
                ),
            )
            latencies.append(time.perf_counter() - started)
            returned_docs = [item.document_id for item in result.evidence]
            expected = set(case.get("expected_document_ids") or [])
            answerable = bool(case.get("answerable", True))

            violations: list[str] = []

            # 越界 1：客户视角不得出现 internal 文档
            if audience is Visibility.CUSTOMER_VISIBLE:
                for item in result.evidence:
                    if item.visibility is Visibility.INTERNAL:
                        violations.append("internal_leak")

            # 越界 2：地区专属文档不得跨地区返回
            for item in result.evidence:
                scoped = REGION_SCOPED_DOCS.get(item.document_id)
                if scoped and case.get("country_code") and case["country_code"] != scoped:
                    violations.append(f"region_leak:{item.document_id}")

            # 越界 3：停用文档不得出现
            for item in result.evidence:
                if item.document_id in DISABLED_DOCS:
                    violations.append(f"disabled_doc:{item.document_id}")
            for forbidden in case.get("forbidden_document_ids") or []:
                if forbidden in returned_docs:
                    violations.append(f"forbidden_doc:{forbidden}")

            hit = None
            if answerable:
                hit = bool(expected & set(returned_docs))

            outcomes.append(
                CaseOutcome(
                    case_id=case["case_id"],
                    question=case["question"],
                    answerable=answerable,
                    hit_at_5=hit,
                    returned_document_ids=returned_docs,
                    returned_chunk_count=len(result.evidence),
                    top_rrf=result.evidence[0].rrf_score if result.evidence else None,
                    hit_status=result.hit_status.value,
                    violations=violations,
                    notes=result.notes,
                )
            )
    finally:
        session.close()
        engine.dispose()

    answerable_cases = [item for item in outcomes if item.answerable]
    negative_cases = [item for item in outcomes if not item.answerable]
    hits = sum(1 for item in answerable_cases if item.hit_at_5)
    violations_total = sum(len(item.violations) for item in outcomes)

    sorted_lat = sorted(latencies)
    # nearest-rank P95：取第 ceil(0.95*n) 个样本（1-based），再转 0-based 索引
    p95_index = max(0, min(len(sorted_lat) - 1, round(0.95 * len(sorted_lat)) - 1))

    summary = {
        "split": split,
        "run_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
        "chunk_config_version": settings.chunk_config_version,
        "retrieval_top_k": settings.retrieval_top_k,
        "retrieval_max_evidence": settings.retrieval_max_evidence,
        "embedding_model_id": settings.embedding_model_id,
        "embedding_backend": settings.embedding_backend,
        # 精排必须写进报告：读报告的人要能分辨"这次结果是否经过重排序"
        "rerank_model": settings.rerank_model if settings.rerank_backend == "http" else None,
        "rerank_backend": settings.rerank_backend,
        "rerank_candidates": settings.rerank_candidates if settings.rerank_backend == "http" else None,
        "run_mode": settings.run_mode,
        "total_cases": len(outcomes),
        "answerable_cases": len(answerable_cases),
        "hit_at_5_numerator": hits,
        "hit_at_5_denominator": len(answerable_cases),
        "hit_at_5": round(hits / len(answerable_cases), 4) if answerable_cases else None,
        "negative_cases": len(negative_cases),
        "negative_cases_with_evidence": sum(
            1 for item in negative_cases if item.returned_chunk_count > 0
        ),
        "filter_violations": violations_total,
        "meets_hit_at_5_target": (
            hits / len(answerable_cases) >= 0.9 if answerable_cases else None
        ),
        # 检索耗时（本地编码 + Qdrant 查询），不含模型生成；用于 AC-16 的分解报告
        "retrieval_latency_p50_seconds": round(sorted_lat[len(sorted_lat) // 2], 3)
        if sorted_lat
        else None,
        "retrieval_latency_p95_seconds": round(sorted_lat[p95_index], 3) if sorted_lat else None,
        "retrieval_latency_max_seconds": round(sorted_lat[-1], 3) if sorted_lat else None,
        "outcomes": [asdict(item) for item in outcomes],
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["calibration", "holdout", "all"], default="calibration")
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--chunk-overlap", type=int, default=None)
    parser.add_argument(
        "--snapshot",
        default=None,
        help="指定快照进行对照评测（不改变当前有效快照）",
    )
    parser.add_argument(
        "--mode",
        choices=["hybrid", "dense_only", "sparse_only"],
        default="hybrid",
        help="检索模式；单路模式用于工程规范第 12.5 节的对照实验",
    )
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    overrides: dict[str, object] = {}
    if args.chunk_size is not None:
        overrides["chunk_size"] = args.chunk_size
    if args.chunk_overlap is not None:
        overrides["chunk_overlap"] = args.chunk_overlap
    settings = Settings(**overrides)  # type: ignore[arg-type]

    splits = ["calibration", "holdout"] if args.split == "all" else [args.split]
    reports = []
    for split in splits:
        report = run_split(split, settings=settings, snapshot_id=args.snapshot, mode=args.mode)
        report["snapshot_id"] = args.snapshot
        reports.append(report)
        print(f"\n===== {split} / mode={args.mode} =====")
        print(
            f"可回答问题 Hit@5 : {report['hit_at_5_numerator']}/{report['hit_at_5_denominator']}"
            f" = {report['hit_at_5']}"
        )
        print(
            f"负例数           : {report['negative_cases']}"
            f"（其中返回了证据的：{report['negative_cases_with_evidence']}）"
        )
        print(f"过滤越界次数     : {report['filter_violations']}")
        print(
            f"检索时延         : p50={report['retrieval_latency_p50_seconds']}s "
            f"p95={report['retrieval_latency_p95_seconds']}s "
            f"max={report['retrieval_latency_max_seconds']}s"
        )
        print(f"配置             : chunk={report['chunk_size']}/{report['chunk_overlap']} "
              f"top_k={report['retrieval_top_k']} max_evidence={report['retrieval_max_evidence']}")
        misses = [item for item in report["outcomes"] if item["answerable"] and not item["hit_at_5"]]
        if misses:
            print(f"未命中（{len(misses)}）：")
            for item in misses:
                print(f"  - {item['case_id']}: {item['question'][:40]}")
                print(f"      返回={item['returned_document_ids']}")
        bad = [item for item in report["outcomes"] if item["violations"]]
        if bad:
            print(f"越界（{len(bad)}）：")
            for item in bad:
                print(f"  - {item['case_id']}: {item['violations']}")

    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out) if args.out else RESULTS_ROOT / f"retrieval-{args.split}-{stamp}.json"
    out_path.write_text(
        json.dumps(
            {
                "note": "本报告基于虚构夹具；不得作为官方业务结论或线上指标。",
                "environment": {
                    "python": sys.version.split()[0],
                    "platform": sys.platform,
                },
                "reports": reports,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n报告已写入：{out_path}")

    ok = all(
        (report["filter_violations"] == 0)
        and (report["hit_at_5"] is None or report["hit_at_5"] >= 0.9)
        for report in reports
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
