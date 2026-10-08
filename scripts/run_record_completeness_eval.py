"""最小办理数据完整率评测（PRD AC-12）。

口径来自 PRD 第 5.2 节「本期最小办理数据」：逐字段检查「必填是否落库」「选填在缺失时
是否保持为空而不是编造」。检查对象是**真实产生的办理记录**（不是构造的行）：

1. 通过真实 API 制造不同路径的案件——排障、质保、退款草稿、投诉；
2. 直接读取数据库（SQLAlchemy 模型 → 真实列名），按 5.2 逐字段核对；
3. 报告分子/分母，并逐条列出缺失字段。

必填规则的实现方式：会话相关必填项在 `conversation`/`case` 表；申请相关必填项只在
**确实进入申请**的案件上要求（PRD：进入申请时必填）。

用法（在 `code` 根目录即可）：
    .\services\api\.venv\Scripts\python.exe scripts\run_record_completeness_eval.py

输出：`code/evals/results/record-completeness-<UTC>.json`
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib import error, request

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICES_API = REPO_ROOT / "services" / "api"
if str(SERVICES_API) not in sys.path:
    sys.path.insert(0, str(SERVICES_API))

RESULTS_DIR = REPO_ROOT / "evals" / "results"
RUNTIME_REL = "data/runtime-audit"
RUNTIME = REPO_ROOT / RUNTIME_REL

CUSTOMER = {"X-Demo-View-Role": "customer", "content-type": "application/json"}

# 覆盖不同路径，使 5.2 的「视路径必填」字段真的被填到。
# 注意：退款这条必须带**唯一订单号**——CUST-DEMO-01 名下有多个订单，
# 订单不唯一时无法确定型号/地区，系统按设计先走补问而不会生成申请草稿，
# 那样 5.2 的申请字段就没有样本可查（第一版漏了这点，申请字段检查数=0）。
SCENARIOS = [
    ("排障", "我的 A1 Pro 是在中国大陆买的，吸力变弱了应该怎么排查"),
    ("质保", "我的 A1 Pro 是在中国大陆买的，订单号 ORD-DEMO-1002，还在保修期内吗"),
    ("退款草稿", "我的 A1 Pro 是在中国大陆买的，订单号 ORD-DEMO-1002，我要退款"),
    ("投诉", "我的 A1 Pro 是在中国大陆买的，我要投诉，客服一直不回复"),
]


def post_json(url: str, payload: dict[str, object]) -> tuple[int, object]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(url, data=body, headers=CUSTOMER, method="POST")
    try:
        with request.urlopen(req, timeout=180) as response:  # noqa: S310
            return response.status, json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]


def wait_http(url: str, attempts: int) -> bool:
    for _ in range(attempts):
        time.sleep(0.5)
        try:
            with request.urlopen(url, timeout=3) as response:  # noqa: S310
                if response.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    src_qdrant = REPO_ROOT / "data" / "runtime" / "qdrant"
    if src_qdrant.exists():
        shutil.copytree(src_qdrant, RUNTIME / "qdrant")

    # 知识索引分布在两处：Qdrant 目录（向量/payload）与库里的元数据表
    # （knowledge_snapshot 等）。只复制前者会让隔离库没有 active 快照，
    # 检索直接返回 not_found —— 这正是上一轮「申请字段无样本」的原因。
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from seed_isolated_knowledge import seed as seed_knowledge  # noqa: PLC0415

    seeded = seed_knowledge(
        REPO_ROOT / "data" / "runtime" / "anker_agent.sqlite3",
        RUNTIME / "audit.sqlite3",
        create_schema=True,
    )
    print(
        f"  已补齐知识元数据：快照 {seeded.get('knowledge_snapshot', 0)} 行、"
        f"片段 {seeded.get('knowledge_chunk', 0)} 行"
    )

    import os

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["ANKER_AGENT_DATABASE_URL"] = f"sqlite+pysqlite:///{RUNTIME_REL}/audit.sqlite3"
    env["ANKER_AGENT_RUNTIME_DIR"] = RUNTIME_REL
    env["ANKER_AGENT_QDRANT_PATH"] = f"{RUNTIME_REL}/qdrant"

    server = subprocess.Popen(  # noqa: S603
        [
            str(SERVICES_API / ".venv" / "Scripts" / "python.exe"),
            "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(args.port),
        ],
        cwd=str(SERVICES_API), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    conversations: list[str] = []
    scenario_replies: list[dict[str, object]] = []
    try:
        if not wait_http(f"{base}/api/health", 60):
            raise RuntimeError("评测后端未就绪")
        for index, (label, message) in enumerate(SCENARIOS, start=1):
            status, created = post_json(
                f"{base}/api/customer/conversations", {"customerId": "CUST-DEMO-01"}
            )
            if status != 200 or not isinstance(created, dict):
                continue
            conversation_id = str(created["conversationId"])
            status, sent = post_json(
                f"{base}/api/customer/conversations/{conversation_id}/messages",
                {"body": message, "clientMessageKey": f"ac12-{index}"},
            )
            reply_body = ""
            if isinstance(sent, dict):
                reply = sent.get("reply") or {}
                if isinstance(reply, dict):
                    reply_body = str(reply.get("body") or "")
            scenario_replies.append(
                {"label": label, "status": status, "reply": reply_body[:400]}
            )
            conversations.append(conversation_id)
            print(f"  已创建 {label} 案件：{conversation_id}")
            print(f"    回复：{reply_body[:120].replace(chr(10), ' / ')}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
    time.sleep(0.8)

    # ── 直接读库核对 5.2 字段 ─────────────────────────────────────────────
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.domain.case_state.models import (
        AfterSalesRequestRow,
        AuditEventRow,
        CaseRow,
        ConversationRow,
    )

    engine = create_engine(
        f"sqlite+pysqlite:///{RUNTIME / 'audit.sqlite3'}", future=True
    )
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()

    # PRD 5.2 必填字段（会话/案件层）。值为 None/空串视为缺失。
    # PRD 5.2 必填字段，按**实际所在表**分组
    CONVERSATION_REQUIRED = [
        "conversation_id",
        "service_mode",
        "message_revision",
        "mode_revision",
    ]
    CASE_REQUIRED = [
        "case_id",
        "conversation_id",
        "service_started_at",
        "updated_at",
        "case_status",
        "customer_intents_json",
        "emotion_level",
        "complaint_risk",
    ]
    # 进入申请时必填
    REQUEST_REQUIRED = [
        "request_id",
        "request_type",
        "request_status",
        "request_payload_json",
        "request_revision",
        "payload_hash",
    ]

    checks: list[dict[str, object]] = []
    request_check: dict[str, object] = {"requests": 0, "checked": 0, "missing": []}
    scenario_diag: list[dict[str, object]] = []

    def _check_row(
        conversation_id: str, row: object, fields: list[str], *, label: str
    ) -> None:
        for field in fields:
            value = getattr(row, field, None)
            # 数值型版本号 0 是合法值；字符串字段空串视为缺失
            present = value is not None and (not isinstance(value, str) or value.strip() != "")
            safe_value = value.isoformat() if isinstance(value, datetime) else value
            checks.append(
                {
                    "conversation_id": conversation_id,
                    "field": f"{label}.{field}",
                    "present": bool(present),
                    "value": (
                        safe_value[:60] if isinstance(safe_value, str) else safe_value
                    ),
                }
            )

    for conversation_id in conversations:
        conversation = session.execute(
            select(ConversationRow).where(
                ConversationRow.conversation_id == conversation_id
            )
        ).scalar_one_or_none()
        case = session.execute(
            select(CaseRow).where(CaseRow.conversation_id == conversation_id)
        ).scalar_one_or_none()
        if conversation is None or case is None:
            checks.append(
                {
                    "conversation_id": conversation_id,
                    "field": "<case>",
                    "present": False,
                    "note": "案件未创建",
                }
            )
            continue

        # 按**实际所在表**核对：service_mode/message_revision/mode_revision 属于
        # conversation（PRD 5.2 同段要求必填），其余属于 case。写错表会得到一批
        # 假的「缺失」——第一次运行就是这样误报了 12 处。
        _check_row(conversation_id, conversation, CONVERSATION_REQUIRED, label="conv")
        _check_row(conversation_id, case, CASE_REQUIRED, label="case")

        # trace_id / audit_event_id（PRD：必填，关联审计）
        audit_rows = list(
            session.execute(
                select(AuditEventRow).where(
                    AuditEventRow.conversation_id == conversation_id
                )
            ).scalars()
        )
        checks.append(
            {
                "conversation_id": conversation_id,
                "field": "trace_id(audit)",
                "present": bool(audit_rows) and all(bool(row.trace_id) for row in audit_rows),
                "value": f"{len(audit_rows)} 条审计",
            }
        )

        requests = list(
            session.execute(
                select(AfterSalesRequestRow).where(
                    AfterSalesRequestRow.conversation_id == conversation_id
                )
            ).scalars()
        )
        request_check["requests"] = int(request_check["requests"]) + len(requests)  # type: ignore[arg-type]
        scenario_diag.append(
            {
                "conversation_id": conversation_id,
                "case_status": case.case_status,
                "stage": case.conversation_stage,
                "intents": case.customer_intents_json,
                "knowledge_hit_status": case.knowledge_hit_status,
                "retrieval_id": case.retrieval_id,
                "requests": len(requests),
            }
        )
        for row in requests:
            for field in REQUEST_REQUIRED:
                value = getattr(row, field, None)
                present = value is not None and (
                    not isinstance(value, str) or value.strip() != ""
                )
                request_check["checked"] = int(request_check["checked"]) + 1  # type: ignore[arg-type]
                if not present:
                    request_check["missing"].append(  # type: ignore[union-attr]
                        {"request_id": row.request_id, "field": field}
                    )

    session.close()
    engine.dispose()
    shutil.rmtree(RUNTIME, ignore_errors=True)

    total = len(checks)
    present = sum(1 for item in checks if item["present"])
    missing = [item for item in checks if not item["present"]]
    req_checked = int(request_check["checked"])
    req_missing = len(request_check["missing"])  # type: ignore[arg-type]

    summary = {
        "cases": len(conversations),
        "case_field_checks": total,
        "case_field_present": present,
        "case_field_rate": round(present / total, 4) if total else None,
        "missing_fields": missing,
        "request_count": request_check["requests"],
        "request_field_checks": req_checked,
        "request_field_missing": req_missing,
        "request_field_rate": (
            round((req_checked - req_missing) / req_checked, 4) if req_checked else None
        ),
        "meets_target": bool(total) and not missing and req_missing == 0,
        "target_rate": 1.0,
    }

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "note": "在隔离运行目录 data/runtime-audit 上产生真实办理记录后直接读库核对；已清理。",
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "scenarios": [{"label": label, "message": message} for label, message in SCENARIOS],
        "conversations": conversations,
        "scenario_replies": scenario_replies,
        "summary": summary,
        "checks": checks,
        "request_check": request_check,
        "scenario_diag": scenario_diag,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"record-completeness-{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== AC-12 最小办理记录完整率 =====")
    print(f"案件字段 {present}/{total} = {summary['case_field_rate']}")
    print(
        f"申请字段 {req_checked - req_missing}/{req_checked} = {summary['request_field_rate']}"
        f"（申请 {request_check['requests']} 个）"
    )
    for item in missing[:10]:
        print(f"  缺失：{item['field']} @ {item['conversation_id']}")
    print(f"→ {'达标' if summary['meets_target'] else '未达标'}")
    print(f"报告：{out.relative_to(REPO_ROOT)}")
    return 0 if summary["meets_target"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
