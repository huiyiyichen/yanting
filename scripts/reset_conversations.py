"""清空会话并重建 5 条干净演示会话。

用户要求（2026-09-26）：「把对话清除掉，只留五个就行了，我一个个删太慢」，
并在确认时选择「全部清空，重建 5 条干净演示会话」。

做法：
1. 直接操作运行的 SQLite（应用层 `delete_conversation` 是逐条 HTTP，792 条太慢），
   删除顺序与外键依赖一致：消息、附件（含磁盘文件）、案件事件、案件、申请、
   话术候选、会话。**审计保留**（与页面删除入口同一口径）。
2. 通过真实 HTTP 接口重建 5 条会话并各发一条真实客户消息（走真实模型与索引），
   让列表里就有 5 条有内容的演示会话；新会话自带开场白与快捷入口。

运行（后端需在 8000 运行）：
    python scripts/reset_conversations.py            # 清空 + 重建
    python scripts/reset_conversations.py --dry-run  # 只统计，不写
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = CODE_ROOT / "services" / "api"
sys.path.insert(0, str(API_ROOT))

BASE = "http://127.0.0.1:8000"
CUSTOMER = {"X-Demo-View-Role": "customer", "Content-Type": "application/json"}
SUPPORT = {"X-Demo-View-Role": "support", "Content-Type": "application/json"}

#: 5 条欧莱雅美妆服务演示会话。
DEMO_MESSAGES: tuple[tuple[str, str], ...] = (
    ("我使用测试修护精华后脸部发红发痒，想请客服协助。", "不良反应"),
    ("我想查询测试轻透粉底液的订单和物流进度。", "物流查询"),
    ("收到的测试睫毛膏包装破损，我想申请换货。", "换货"),
    ("我想查询退运费打款进度。", "打款查询"),
    ("我不想跟机器人说了，我要转人工客服。", "转人工"),
)


def _post(path: str, payload: dict, headers: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode("utf-8", "replace")[:200]}


def purge_conversations() -> dict[str, int]:
    """删除全部会话及其依赖业务数据（审计保留）。"""

    from sqlalchemy import delete, select

    from app.config import get_settings
    from app.db import build_engine, build_session_factory
    from app.domain.case_state.models import (
        AfterSalesRequestRow,
        AiSuggestionRow,
        AttachmentRow,
        CaseEventRow,
        CaseRow,
        ConversationRow,
        MessageRow,
    )

    settings = get_settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    counts: dict[str, int] = {}

    with factory() as session:
        conversation_ids = list(session.execute(select(ConversationRow.conversation_id)).scalars())
        case_ids = list(session.execute(select(CaseRow.case_id)).scalars())
        attachments = list(session.execute(select(AttachmentRow)).scalars())

        # 附件文件先删（数据库行删掉后就找不到路径了）
        from app.repositories.conversation_repository import ConversationRepository

        repo = ConversationRepository(session)
        stored_paths = [str(row.stored_path) for row in attachments]
        if stored_paths:
            removed_files = repo._delete_attachment_files(stored_paths)  # noqa: SLF001
            counts["attachment_files"] = removed_files

        counts["messages"] = session.execute(delete(MessageRow)).rowcount or 0
        counts["attachments"] = session.execute(delete(AttachmentRow)).rowcount or 0
        counts["suggestions"] = session.execute(delete(AiSuggestionRow)).rowcount or 0
        counts["case_events"] = session.execute(delete(CaseEventRow)).rowcount or 0
        counts["requests"] = session.execute(delete(AfterSalesRequestRow)).rowcount or 0
        counts["cases"] = session.execute(delete(CaseRow)).rowcount or 0
        counts["conversations"] = session.execute(delete(ConversationRow)).rowcount or 0
        session.commit()

    counts["case_ids_seen"] = len(case_ids)
    counts["conversation_ids_seen"] = len(conversation_ids)
    engine.dispose()
    return counts


def seed_demo_conversations() -> list[str]:
    created: list[str] = []
    for index, (body, _label) in enumerate(DEMO_MESSAGES, start=1):
        status, payload = _post("/api/customer/conversations", {}, CUSTOMER)
        if status != 200:
            print(f"  第 {index} 条会话创建失败：HTTP {status} {payload}")
            continue
        conversation_id = payload["conversationId"]
        status, response = _post(
            f"/api/customer/conversations/{conversation_id}/messages",
            {"body": body, "clientMessageKey": f"demo-{index}-{int(time.time())}"},
            CUSTOMER,
        )
        reply = ""
        if isinstance(response, dict) and isinstance(response.get("reply"), dict):
            reply = str(response["reply"].get("body") or "")
        print(
            f"  [{index}] {conversation_id} HTTP {status} | 客户：{body[:24]}… | "
            f"回复 {len(reply)} 字"
        )
        created.append(conversation_id)
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description="清空会话并重建 5 条演示会话")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    parser.add_argument("--skip-seed", action="store_true", help="只清空，不重建")
    args = parser.parse_args()

    if args.dry_run:
        request = urllib.request.Request(
            f"{BASE}/api/customer/conversations?customer_id=CUST-DEMO-01", headers=CUSTOMER
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            rows = json.loads(response.read().decode("utf-8"))
        print(f"当前会话数：{len(rows)}（dry-run，未做任何修改）")
        return 0

    print("清空会话与依赖业务数据（审计保留）…")
    counts = purge_conversations()
    print("  删除：", json.dumps(counts, ensure_ascii=False))

    if not args.skip_seed:
        print("重建 5 条演示会话（真实模型与索引）…")
        created = seed_demo_conversations()
        print(f"  已重建 {len(created)} 条")

    # 客服侧队列与客户列表都以服务端为准，这里顺带核对一次
    request = urllib.request.Request(f"{BASE}/api/support/queue", headers=SUPPORT)
    with urllib.request.urlopen(request, timeout=30) as response:
        queue = json.loads(response.read().decode("utf-8"))
    print(f"客服队列剩余：{len(queue)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
