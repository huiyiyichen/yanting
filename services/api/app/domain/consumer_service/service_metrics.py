"""服务指标（改进方案 P1-9）。只读，不调用模型。

- AI 接待：有过自动接待任务的会话数。
- 自动回复率：sent /(sent + handoff) 的任务数；无任务时为空。
- 转人工：handoff 任务按原因归为客户要求、安全复核、模型失败三类。
- 平均首响：本地会话首条消费者消息到首条实际服务回复（AI 或客服）的时长；开场白早于消费者消息，不计。
- 建议采纳率：已处理（采用或忽略）的建议中采用的比例；无记录时为空。
"""

from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

HANDOFF_GROUPS = {
    "customer_requested": "customer", "operator_takeover": "customer",
    "safety_review": "safety", "unsupported_image": "safety", "invalid_reply": "safety",
    "model_requested": "safety",
    "model_unavailable": "model_failure", "generation_failed": "model_failure", "reply_timeout": "model_failure",
}


def reception_metrics(session: Session) -> dict:
    from app.domain.case_state.models import AuditEventRow, MessageRow
    from app.domain.consumer_service.models import AutoReplyJobRow

    jobs = list(session.scalars(select(AutoReplyJobRow)))
    sent = sum(job.status == "sent" for job in jobs)
    handoff_jobs = [job for job in jobs if job.status == "handoff"]
    groups = defaultdict(int)
    for job in handoff_jobs:
        groups[HANDOFF_GROUPS.get(job.error_code or "", "safety")] += 1

    first_customer: dict[str, object] = {}
    first_reply: dict[str, object] = {}
    for message in session.scalars(select(MessageRow).order_by(MessageRow.created_at)):
        cid = message.conversation_id
        if message.sender_role == "customer" and message.body is not None:
            first_customer.setdefault(cid, message.created_at)
        elif message.sender_role in {"assistant", "operator"} and cid in first_customer:
            first_reply.setdefault(cid, message.created_at)
    waits = [(first_reply[cid] - first_customer[cid]).total_seconds() for cid in first_reply]

    adopted = ignored = 0
    for row in session.scalars(select(AuditEventRow).where(AuditEventRow.event_type == "consumer_suggestion_action")):
        action = json.loads(row.detail_json or "{}").get("action")
        adopted += action == "adopt"
        ignored += action == "ignore"
    return {
        "ai_conversations": len({job.conversation_id for job in jobs}),
        "auto_reply_rate": round(sent / (sent + len(handoff_jobs)), 4) if sent + len(handoff_jobs) else None,
        "handoffs": {"total": len(handoff_jobs), "customer": groups["customer"], "safety": groups["safety"],
                     "model_failure": groups["model_failure"]},
        "average_first_response_seconds": round(sum(waits) / len(waits), 1) if waits else None,
        "suggestion_adoption_rate": round(adopted / (adopted + ignored), 4) if adopted + ignored else None,
    }
