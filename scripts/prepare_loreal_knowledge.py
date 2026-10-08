"""Build source-backed product documents and publish through the existing Qdrant pipeline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))

from sqlalchemy import select  # noqa: E402

from app.domain.consumer_service.models import ServiceOrderRow  # noqa: E402
from app.domain.consumer_service.workspace import active_batch  # noqa: E402
from app.knowledge.ingest import ingest_manifest, load_manifest  # noqa: E402
from app.runtime import build_runtime  # noqa: E402


def main() -> None:
    runtime = build_runtime()
    session = runtime.new_session()
    try:
        root = ROOT / "data/knowledge/loreal"
        path = root / "manifest.json"
        load_manifest(path)
        products = {}
        for row in session.scalars(
            select(ServiceOrderRow).where(ServiceOrderRow.batch_id == active_batch(session))
        ):
            products[(row.sku, row.product_name)] = row
        lines = ["# 官方虚构商品目录", "", "来源：赛题一业务数据 Excel 的订单表。", ""]
        for (sku, name), row in sorted(products.items()):
            lines.extend(
                [
                    f"## {name}",
                    f"货号：{sku}",
                    f"订单单价：{row.unit_price_minor / 100:.2f} 元",
                    "成分、功效与适用性：源文件未提供，不作判断。",
                    "",
                ]
            )
        (root / "products.md").write_text("\n".join(lines), encoding="utf-8")
        report = ingest_manifest(
            session,
            settings=runtime.settings,
            embedding_provider=runtime.embedding_provider,
            manifest_path=path,
            restrict_to_manifest=True,
        )
        session.commit()
        print(json.dumps(report.to_dict(), ensure_ascii=False))
    finally:
        session.close()
        runtime.close()


if __name__ == "__main__":
    main()
