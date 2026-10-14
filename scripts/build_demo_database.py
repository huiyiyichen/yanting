"""构建演示库快照（改进方案 P0-4）。

步骤（全部幂等，只写演示文件，不碰主运行库 data/runtime/anker_agent.sqlite3）：
1. 删除并重建 `data/runtime/demo-snapshot.sqlite3`；
2. 从官方 Excel 导入聊天、订单与五类工单，写入内置 Prompt 模板；
3. 发布当前美妆知识快照到 `data/runtime/demo-qdrant`（需要编码模型；`--skip-knowledge` 跳过）；
4. 按 `data/demo/storylines.json` 写入剧情化本地会话（不调用模型，不产生自动接待任务）；
5. 执行一次风险规则扫描，输出各剧情会话与计数。

用法：
    python -X utf8 scripts/build_demo_database.py [--skip-knowledge] [--source <Excel>]
随后用 `scripts/reset_demo.ps1` 把快照复制为 `data/runtime/demo.sqlite3`，
再用 `start-demo.cmd`（等价于 `start_loreal_demo.ps1 -Profile demo`）启动。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.config import Settings, official_source_path  # noqa: E402

RUNTIME = REPO / "data" / "runtime"
SNAPSHOT = RUNTIME / "demo-snapshot.sqlite3"
SNAPSHOT_QDRANT = RUNTIME / "demo-snapshot-qdrant"
STORYLINES = REPO / "data" / "demo" / "storylines.json"
TEST_MARKERS = ("QUALITY-", "联动", "验证", "测试会话", "99999999", "[e2e", "检查：")


def _sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.as_posix()}"


def build_database(source: Path) -> dict:
    from app.db import build_engine, build_session_factory
    from app.domain.case_state.models import Base as CaseBase
    from app.domain.consumer_service import models as consumer_models
    from app.domain.consumer_service.importer import import_business_workbook
    from app.domain.platform.settings import ensure_builtin_templates
    from app.knowledge.models import Base as KnowledgeBase

    settings = Settings(database_url=_sqlite_url(SNAPSHOT))
    engine = build_engine(settings)
    consumer_models.migrate_risk_alert_table(engine)
    CaseBase.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as session:
        report = import_business_workbook(session, source, repo_root=REPO)
        ensure_builtin_templates(session)
        session.commit()
    engine.dispose()
    return {"import": {"batchId": report.batch_id, "counts": report.counts,
                       "qualityStatus": report.report.get("qualityStatus")}}


def publish_knowledge() -> dict:
    env = {
        **os.environ,
        "ANKER_AGENT_DATABASE_URL": _sqlite_url(SNAPSHOT),
        "ANKER_AGENT_QDRANT_PATH": SNAPSHOT_QDRANT.relative_to(REPO).as_posix(),
        "PYTHONIOENCODING": "utf-8",
    }
    completed = subprocess.run(
        [sys.executable, "-X", "utf8", str(REPO / "scripts" / "prepare_loreal_knowledge.py")],
        env=env, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"知识发布失败，快照未完成：{completed.stderr.strip()[-600:]}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


def seed_storylines(now: datetime) -> list[dict]:
    from app.db import build_engine, build_session_factory
    from app.domain.case_state.models import ConversationRow, MessageRow
    from app.domain.consumer_service.risk_rules import evaluate_risks

    plan = json.loads(STORYLINES.read_text(encoding="utf-8"))
    engine = build_engine(Settings(database_url=_sqlite_url(SNAPSHOT)))
    factory = build_session_factory(engine)
    seeded = []
    with factory() as session:
        for story in plan["local"]:
            start = now - timedelta(minutes=story["minutesAgo"])
            last = start + timedelta(minutes=max(m["at"] for m in story["messages"]))
            session.add(ConversationRow(
                conversation_id=story["conversationId"], customer_id=story["customerId"],
                title=story["title"], service_mode="autonomous", message_revision=len(story["messages"]),
                created_at=start, updated_at=last,
            ))
            session.flush()
            for index, message in enumerate(story["messages"]):
                session.add(MessageRow(
                    message_id=f"{story['conversationId']}-m{index + 1:02d}",
                    conversation_id=story["conversationId"], sender_role=message["role"],
                    body=message["body"], client_message_key=f"demo-{story['story']}-{index + 1}",
                    created_at=start + timedelta(minutes=message["at"]),
                ))
            seeded.append({"story": story["story"], "conversationId": story["conversationId"],
                           "messages": len(story["messages"])})
        session.commit()
        evaluate_risks(session)
        session.commit()
    engine.dispose()
    return seeded


def audit_snapshot() -> dict:
    """演示库不得出现测试命名的会话或工单。"""
    import sqlite3

    with sqlite3.connect(SNAPSHOT) as connection:
        titles = [row[0] or "" for row in connection.execute("select title from conversation")]
        tickets = [row[0] or "" for row in connection.execute("select title from service_ticket")]
        conversations = connection.execute("select count(*) from service_conversation").fetchone()[0]
        alerts = connection.execute("select count(*) from service_risk_alert").fetchone()[0]
    polluted = [t for t in titles + tickets if any(marker in t for marker in TEST_MARKERS)]
    if polluted:
        raise SystemExit(f"演示库含测试命名记录：{polluted[:5]}")
    return {"localConversations": len(titles), "localTickets": len(tickets),
            "officialConversations": conversations, "riskAlerts": alerts}


def main() -> int:
    parser = argparse.ArgumentParser(description="构建颜听演示库快照")
    parser.add_argument("--source", default=str(official_source_path()), help="官方 Excel 路径")
    parser.add_argument("--skip-knowledge", action="store_true", help="不发布知识快照（无编码模型时）")
    args = parser.parse_args()
    source = Path(args.source)
    if not source.exists():
        parser.error(f"找不到官方 Excel：{source}；放到 data/source/ 或用 --source 指定")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    for path in (SNAPSHOT, SNAPSHOT.with_suffix(".sqlite3-wal"), SNAPSHOT.with_suffix(".sqlite3-shm")):
        path.unlink(missing_ok=True)
    shutil.rmtree(SNAPSHOT_QDRANT, ignore_errors=True)

    result = {"snapshot": str(SNAPSHOT.relative_to(REPO)), **build_database(source)}
    result["knowledge"] = "skipped" if args.skip_knowledge else publish_knowledge()
    result["storylines"] = seed_storylines(datetime.now(UTC))
    result["audit"] = audit_snapshot()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
