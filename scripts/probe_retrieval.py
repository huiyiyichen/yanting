"""检索探针：按查询与过滤条件执行混合检索并打印证据。

用途：S1 校准与留出评测的取证工具，也用于人工核对证据来源与适用条件。

用法：
    python scripts/probe_retrieval.py --query "吸尘器没有吸力了怎么排查"
    python scripts/probe_retrieval.py --query "质保多久" --model "A1 Pro" --country CN
    python scripts/probe_retrieval.py --query "退货条件" --audience internal
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.config import Settings  # noqa: E402
from app.db import build_engine, build_session_factory  # noqa: E402
from app.domain.enums import Visibility  # noqa: E402
from app.integrations.embedding_provider import build_embedding_provider  # noqa: E402
from app.knowledge.retrieval import RetrievalRequest, retrieve  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--audience", choices=["customer", "internal"], default="customer")
    parser.add_argument("--model", default=None, help="已确认产品型号")
    parser.add_argument("--country", default=None, help="已确认国家/地区代码")
    parser.add_argument("--channel", default=None, help="已确认购买渠道")
    parser.add_argument(
        "--mode",
        choices=["hybrid", "dense_only", "sparse_only"],
        default="hybrid",
        help="检索模式（对照实验用）",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    provider = build_embedding_provider(settings)
    session = factory()
    try:
        result = retrieve(
            session,
            settings=settings,
            embedding_provider=provider,
            request=RetrievalRequest(
                query=args.query,
                audience=(
                    Visibility.INTERNAL if args.audience == "internal" else Visibility.CUSTOMER_VISIBLE
                ),
                product_model=args.model,
                country_code=args.country,
                purchase_channel=args.channel,
                mode=args.mode,  # type: ignore[arg-type]
            ),
        )
    finally:
        session.close()
        engine.dispose()

    if args.json:
        print(
            json.dumps(
                {
                    "retrieval_id": result.retrieval_id,
                    "snapshot_id": result.snapshot_id,
                    "hit_status": result.hit_status.value,
                    "candidates": result.candidates_considered,
                    "filter": result.filter_summary,
                    "notes": result.notes,
                    "evidence": [item.model_dump(mode="json") for item in result.evidence],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"query       : {args.query}")
    print(f"audience    : {args.audience}")
    print(f"snapshot    : {result.snapshot_id}")
    print(f"hit_status  : {result.hit_status.value}")
    print(f"candidates  : {result.candidates_considered}")
    print(f"filter      : {json.dumps(result.filter_summary, ensure_ascii=False)}")
    for note in result.notes:
        print(f"note        : {note}")
    print(f"evidence    : {len(result.evidence)}")
    for index, item in enumerate(result.evidence, start=1):
        ranks = item.channel_ranks
        print(
            f"\n[{index}] rrf={item.rrf_score:.4f} dense={ranks.get('dense')} sparse={ranks.get('sparse')}"
        )
        print(f"    文档   : {item.document_title} @{item.document_version} ({item.visibility.value})")
        print(f"    路径   : {item.heading_path}")
        print(f"    定位   : {item.source_locator}")
        print(f"    适用   : {json.dumps(item.applicability, ensure_ascii=False)}")
        print(f"    摘录   : {item.quoted_excerpt[:160]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
