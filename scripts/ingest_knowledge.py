"""知识导入命令行入口（受控本地导入）。

用法：
    python scripts/ingest_knowledge.py                 # 导入并激活快照
    python scripts/ingest_knowledge.py --no-activate   # 只写暂存快照
    python scripts/ingest_knowledge.py --manifest <path>

设计说明（工程规范第 12.1 节）：本期用**受控本地导入入口**管理资料，
不新增知识管理后台页面；导入走同一进程，避免多进程争用 Qdrant local 文件锁。
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
from app.integrations.embedding_provider import build_embedding_provider  # noqa: E402
from app.knowledge.ingest import ingest_manifest  # noqa: E402
from app.knowledge.models import Base  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="导入知识清单并发布快照")
    parser.add_argument(
        "--manifest",
        default=str(REPO / "data" / "knowledge" / "manifest.json"),
        help="清单路径",
    )
    parser.add_argument("--no-activate", action="store_true", help="只写暂存快照，不激活")
    parser.add_argument("--chunk-size", type=int, default=None, help="覆盖切片目标长度")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="覆盖切片重叠")
    parser.add_argument("--json", action="store_true", help="只输出 JSON 报告")
    parser.add_argument("--out", default=None, help="把 JSON 报告写入指定文件")
    args = parser.parse_args()

    overrides: dict[str, object] = {}
    if args.chunk_size is not None:
        overrides["chunk_size"] = args.chunk_size
        overrides["chunk_config_version"] = (
            f"chunk-{args.chunk_size}-{args.chunk_overlap if args.chunk_overlap is not None else 80}-v1"
        )
    if args.chunk_overlap is not None:
        overrides["chunk_overlap"] = args.chunk_overlap

    settings = Settings(**overrides)  # type: ignore[arg-type]
    manifest_path = Path(args.manifest).resolve()
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    provider = build_embedding_provider(settings)

    if not provider.available():
        print(
            json.dumps(
                {
                    "result": "FAILED_EMBEDDING_UNAVAILABLE",
                    "detail": provider.describe(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    session = factory()
    try:
        report = ingest_manifest(
            session,
            settings=settings,
            embedding_provider=provider,
            manifest_path=manifest_path,
            knowledge_root=manifest_path.parent,
            activate=not args.no_activate,
        )
        session.commit()
        payload = report.to_dict()
    except Exception as exc:
        session.rollback()
        print(
            json.dumps(
                {"result": "FAILED", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    finally:
        session.close()
        engine.dispose()

    if args.out:
        # 供对照实验等自动化流程读取；同时保留 stdout 报告便于人工核对
        Path(args.out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"snapshot: {payload['snapshot_id']} ({payload['snapshot_status']})")
        print(f"collection: {payload['collection']}")
        print(
            f"chunking: size={payload['chunk_size']} overlap={payload['chunk_overlap']} "
            f"max={payload['max_chunk_chars']} mean={payload['mean_chunk_chars']}"
        )
        print(f"dimension: {payload['vector_dimension']}")
        print(
            f"documents: total={payload['documents_total']} "
            f"imported={payload['documents_imported']} "
            f"skipped={payload['documents_skipped']} "
            f"failed={payload['documents_failed']}"
        )
        print(f"chunks: {payload['chunks_created']}")
        for item in payload["documents"]:  # type: ignore[index]
            flag = "OK " if item["status"] in {"imported", "skipped_duplicate"} else "!! "
            print(
                f"  {flag}{item['document_id']}@{item['document_version']} "
                f"[{item['status']}] chunks={item['chunk_count']}"
                + (f" error={item['error_code']}" if item["error_code"] else "")
            )
        if payload["error_code"]:
            print(f"error: {payload['error_code']} :: {payload['error_detail']}")

    return 0 if payload["snapshot_status"] in {"active", "staging"} else 1


if __name__ == "__main__":
    sys.exit(main())
