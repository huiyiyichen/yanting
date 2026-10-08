"""为隔离运行库补齐知识元数据（供 e2e / 评测脚本使用）。

**为什么需要**：知识索引分布在**两处**——

- Qdrant（本地目录）：向量与 payload，集合名由 `knowledge_snapshot.qdrant_collection` 指定；
- SQLite：`knowledge_base` / `knowledge_document` / `knowledge_chunk` / `knowledge_snapshot`
  / `knowledge_import_run` 这些**元数据**。

只复制 Qdrant 目录、不复制这几张表时，隔离库里没有 active 快照，
`get_active_snapshot()` 返回 `None`，检索直接判 `not_found`（`retrieval.py` 里
"尚未发布任何知识快照"），Qdrant 里那份索引根本不会被打开。
这正是「隔离环境检索 not_found」的根因。

用法（在 `code` 根目录）：
    python scripts/seed_isolated_knowledge.py --target-db data/runtime-e2e/e2e.sqlite3
    python scripts/seed_isolated_knowledge.py --target-db <路径> --create-schema
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 需要随索引一起复制的元数据表（顺序即插入顺序，满足外键方向）
KNOWLEDGE_TABLES = (
    "knowledge_base",
    "knowledge_document",
    "knowledge_snapshot",
    "knowledge_chunk",
    "knowledge_import_run",
)


def seed(source_db: Path, target_db: Path, *, create_schema: bool) -> dict[str, int]:
    if not source_db.exists():
        raise FileNotFoundError(f"源库不存在：{source_db}")

    target_db.parent.mkdir(parents=True, exist_ok=True)

    if create_schema:
        # 用 ORM 建表，保证与模型一致（而不是手写 DDL）。
        # 注意：案件状态与知识库各自声明了**独立的 DeclarativeBase**，
        # 只 create_all 其中一个会漏掉 knowledge_* 五张表（已实测踩到）。
        sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
        from app.config import Settings  # noqa: PLC0415
        from app.db import build_engine  # noqa: PLC0415
        from app.domain.case_state.models import Base as CaseBase  # noqa: PLC0415
        from app.knowledge.models import Base as KnowledgeBase  # noqa: PLC0415

        url = f"sqlite+pysqlite:///{target_db.as_posix()}"
        engine = build_engine(Settings(database_url=url))
        CaseBase.metadata.create_all(engine)
        KnowledgeBase.metadata.create_all(engine)
        engine.dispose()

    src = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    dst = sqlite3.connect(target_db)
    copied: dict[str, int] = {}
    try:
        dst.execute("PRAGMA foreign_keys=ON")
        for table in KNOWLEDGE_TABLES:
            exists = dst.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                copied[table] = -1  # 目标表不存在，跳过
                continue
            rows = src.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
            if not rows:
                copied[table] = 0
                continue
            columns = [item[1] for item in src.execute(f"PRAGMA table_info({table})")]
            placeholders = ",".join("?" for _ in columns)
            dst.executemany(
                f"INSERT OR REPLACE INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                rows,
            )
            copied[table] = len(rows)
        dst.commit()
    finally:
        src.close()
        dst.close()
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-db",
        default=str(REPO_ROOT / "data" / "runtime" / "anker_agent.sqlite3"),
        help="已发布知识快照的库（默认开发库）",
    )
    parser.add_argument("--target-db", required=True, help="要写入的隔离库路径")
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="目标库为空时先建表（ORM 建表，保证与模型一致）",
    )
    args = parser.parse_args()

    copied = seed(Path(args.source_db), Path(args.target_db), create_schema=args.create_schema)
    for table, count in copied.items():
        note = "（目标无此表，已跳过）" if count < 0 else f"{count} 行"
        print(f"  {table:26} {note}")

    snapshots = copied.get("knowledge_snapshot", 0)
    if snapshots <= 0:
        print("警告：没有复制到任何快照，隔离库检索仍会返回 not_found")
        return 1
    print(f"OK：已为 {args.target_db} 补齐知识元数据（快照 {snapshots} 行）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
