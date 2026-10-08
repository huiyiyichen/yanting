"""Import the official fictional L'Oreal business workbook.

Examples:
    python scripts/import_business_data.py
    python scripts/import_business_data.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.config import Settings  # noqa: E402
from app.db import build_engine, build_session_factory, commit_with_retry  # noqa: E402
from app.domain.case_state.models import Base as CaseBase  # noqa: E402
from app.domain.consumer_service import models as _consumer_models  # noqa: E402
from app.domain.consumer_service.importer import (  # noqa: E402
    ImportValidationError,
    import_business_workbook,
)
from app.knowledge.models import Base as KnowledgeBase  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="导入欧莱雅官方虚构业务数据")
    parser.add_argument(
        "--source",
        default=r"D:\下载\赛题 1：数据共情者-业务数据.xlsx",
        help="Excel 源文件",
    )
    parser.add_argument("--database-url", default=None, help="覆盖 SQLite 数据库地址")
    parser.add_argument("--report-out", default=None, help="复制质量报告到指定路径")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    args = parser.parse_args()

    settings = Settings(**({"database_url": args.database_url} if args.database_url else {}))
    engine = build_engine(settings)
    _consumer_models.migrate_risk_alert_table(engine)
    CaseBase.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = build_session_factory(engine)
    session = factory()
    try:
        result = import_business_workbook(session, Path(args.source), repo_root=REPO)
        if not result.reused:
            commit_with_retry(session)
        if args.report_out:
            report_path = Path(args.report_out).resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(result.report, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        payload = {
            "result": "REUSED" if result.reused else "PUBLISHED",
            "batchId": result.batch_id,
            "sourceSha256": result.source_sha256,
            "snapshotPath": result.snapshot_path,
            "reportPath": result.report_path,
            "counts": result.counts,
            "qualityStatus": result.report["qualityStatus"],
            "issues": result.report["issues"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=None if args.json else 2))
        return 0
    except ImportValidationError as exc:
        session.rollback()
        print(
            json.dumps(
                {
                    "result": "REJECTED",
                    "reportPath": str(REPO / "data" / "normalized" / "loreal"),
                    "qualityStatus": exc.report["qualityStatus"],
                    "issues": exc.report["issues"],
                },
                ensure_ascii=False,
                indent=None if args.json else 2,
            )
        )
        return 2
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
