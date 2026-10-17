"""客服采用建议后发送：把那次生成的引用关联到发出的消息（追溯 T4）。"""

from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.logging_setup import get_logger

_log = get_logger(__name__)


def link_adopted_citations(session: Session, conversation_id: str, message_id: str, body: str) -> int:
    """Link the most recent adoption (since the last operator message) to ``message_id``."""
    from app.audit.trace_models import AgentTraceRow, ReplyCitationRow
    from app.domain.case_state.models import AuditEventRow

    try:
        events = list(session.scalars(
            select(AuditEventRow).where(
                AuditEventRow.conversation_id == conversation_id,
                AuditEventRow.event_type.in_(("consumer_suggestion_action", "operator_message")),
            ).order_by(AuditEventRow.created_at.desc()).limit(5)
        ))
        # The current send's own operator_message event is written just before this call.
        events = [e for e in events if json.loads(e.detail_json or "{}").get("messageId") != message_id]
        if not events or events[0].event_type != "consumer_suggestion_action":
            return 0
        detail = json.loads(events[0].detail_json or "{}")
        trace_id, style = detail.get("traceId"), detail.get("style")
        if not trace_id or detail.get("action") not in {"adopt", "adopt_edited"}:
            return 0
        rows = list(session.scalars(select(ReplyCitationRow).where(
            ReplyCitationRow.trace_id == trace_id, ReplyCitationRow.reply_style == style,
            ReplyCitationRow.message_id.is_(None),
        )))
        kept = [r for r in rows if detail.get("action") == "adopt" or r.segment_text in body]
        with session.begin_nested():
            for row in kept:
                row.message_id = message_id
            session.execute(update(AgentTraceRow).where(AgentTraceRow.trace_id == trace_id)
                            .values(outcome_message_id=message_id))
            session.flush()
        return len(kept)
    except Exception:  # tracing never blocks sending
        _log.exception("link adopted citations failed conversation=%s", conversation_id)
        return 0
