"""AI reception with durable jobs and revision-guarded delivery."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.audit.recorder import AuditContext, AuditRecorder
from app.domain.case_state.models import ConversationRow, MessageRow, new_id
from app.domain.consumer_service.models import AutoReplyJobRow, ReceptionHandoffRow
from app.domain.enums import SenderRole, ServiceMode
from app.errors import ConflictError, ModelOutputInvalid, ProviderTimeout
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.conversation import ServiceModeView

_locks: dict[str, Lock] = {}
_registry_lock = Lock()
HANDOFF_REASONS = {
    "customer_requested": "客户要求人工",
    "operator_takeover": "客服主动接管",
    "safety_review": "需要人工复核",
    "model_unavailable": "模型不可用",
    "generation_failed": "模型回复失败",
    "unsupported_image": "图片待人工核实",
    "invalid_reply": "回复依据待核实",
    "model_requested": "AI建议人工跟进",
    "reply_timeout": "AI回复超时",
}


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def remaining_job_seconds(runtime: Any, job: AutoReplyJobRow) -> float:
    elapsed = (utcnow() - job.created_at.replace(tzinfo=None)).total_seconds()
    return runtime.settings.auto_reply_timeout_seconds - elapsed


def wants_human(text: str) -> bool:
    parts = re.split(r"[。！？!?，,；;\n]", text)
    return any(
        re.search(r"(转人工|人工客服|真人客服|找人工|人工服务)", part)
        and not re.search(r"(不用|不要|不需要|无需|不想).{0,5}(转人工|人工|真人)", part)
        for part in parts
    )


def latest_jobs(session: Session) -> dict[str, AutoReplyJobRow]:
    rows = session.scalars(
        select(AutoReplyJobRow).order_by(
            AutoReplyJobRow.created_at,
            AutoReplyJobRow.mode_revision,
            AutoReplyJobRow.message_revision,
        )
    )
    return {row.conversation_id: row for row in rows}


def change_mode(
    session: Session,
    conversation_id: str,
    mode: ServiceMode,
    *,
    actor: str,
    reason: str = "operator_takeover",
    expected_mode_revision: int | None = None,
    expected_message_revision: int | None = None,
    transition_reply: str | None = None,
) -> ServiceModeView:
    from app.domain.consumer_service.workspace import ensure_local_conversation

    conversation = ensure_local_conversation(session, conversation_id)
    before = conversation.service_mode
    if expected_mode_revision is not None:
        claimed = session.execute(
            update(ConversationRow).where(
                ConversationRow.conversation_id == conversation_id,
                ConversationRow.service_mode == ServiceMode.AUTONOMOUS.value,
                ConversationRow.mode_revision == expected_mode_revision,
                ConversationRow.message_revision == expected_message_revision,
            ).values(
                service_mode=mode.value, mode_revision=ConversationRow.mode_revision + 1,
                updated_at=utcnow(),
            )
        )
        if claimed.rowcount != 1:
            raise ConflictError("服务模式或消息已变化")
        session.refresh(conversation)
        changed = True
    else:
        changed = ConversationRepository(session).set_service_mode(conversation, mode)
    if changed:
        if transition_reply:
            ConversationRepository(session).append_message(
                conversation, sender_role=SenderRole.ASSISTANT, body=transition_reply,
                client_message_key=f"handoff-reply:{conversation.mode_revision}",
            )
        session.execute(
            update(AutoReplyJobRow)
            .where(
                AutoReplyJobRow.conversation_id == conversation_id,
                AutoReplyJobRow.status.in_(["queued", "running"]),
            )
            .values(status="cancelled", updated_at=utcnow())
        )
        AuditRecorder(session).record(
            AuditContext.new_turn(actor_type=actor, conversation_id=conversation_id),
            event_type="service_mode_changed",
            detail={
                "fromMode": before,
                "toMode": mode.value,
                "modeRevision": conversation.mode_revision,
                "reason": reason,
            },
        )
    if mode is ServiceMode.OPERATOR_ASSISTED:
        handoff = session.get(ReceptionHandoffRow, conversation_id)
        if handoff is None:
            handoff = ReceptionHandoffRow(conversation_id=conversation_id)
            session.add(handoff)
        handoff.reason, handoff.actor, handoff.created_at = reason, actor, utcnow()
        if changed:
            ConversationRepository(session).append_message(
                conversation,
                sender_role=SenderRole.SYSTEM,
                body="已转人工，客服将继续跟进。",
                client_message_key=f"handoff:{conversation.mode_revision}",
            )
    else:
        handoff = session.get(ReceptionHandoffRow, conversation_id)
        if handoff:
            session.delete(handoff)
        # Switching mode does not replay already-handled customer messages.
        if changed:
            ConversationRepository(session).append_message(
                conversation,
                sender_role=SenderRole.SYSTEM,
                body="AI 接待已恢复。",
                client_message_key=f"resume:{conversation.mode_revision}",
            )
    session.flush()
    return ServiceModeView(
        conversation_id=conversation_id,
        service_mode=mode,
        mode_revision=conversation.mode_revision,
    )


def enqueue_reply(session: Session, conversation: ConversationRow, message: MessageRow) -> None:
    if wants_human(message.body or ""):
        change_mode(
            session,
            conversation.conversation_id,
            ServiceMode.OPERATOR_ASSISTED,
            actor="customer",
            reason="customer_requested",
        )
        return
    if conversation.service_mode != ServiceMode.AUTONOMOUS.value:
        return
    session.execute(
        update(AutoReplyJobRow)
        .where(
            AutoReplyJobRow.conversation_id == conversation.conversation_id,
            AutoReplyJobRow.status == "queued",
        )
        .values(status="superseded", updated_at=utcnow())
    )
    session.add(
        AutoReplyJobRow(
            job_id=f"auto-{uuid4().hex}",
            conversation_id=conversation.conversation_id,
            trigger_message_id=message.message_id,
            message_revision=conversation.message_revision,
            mode_revision=conversation.mode_revision,
        )
    )
    session.flush()


def _eligible(conversation: ConversationRow | None, job: AutoReplyJobRow) -> bool:
    return bool(
        conversation
        and conversation.service_mode == ServiceMode.AUTONOMOUS.value
        and conversation.mode_revision == job.mode_revision
        and conversation.message_revision == job.message_revision
    )


def _safety_handoff(text: str) -> bool:
    """Only the current message decides; an open adverse-reaction ticket alone does not."""
    from app.domain.consumer_service.emotion import has_complaint_signal

    serious = any(term in text for term in ("呼吸困难", "喉咙肿", "去医院", "已经就医", "脸肿"))
    return serious or has_complaint_signal(text)


def validate_auto_reply(body: str, context: Any, *, claims=None, sources=None) -> None:
    """Conservative automatic-send gate; uncertain factual claims go to a person."""
    if claims is not None and sources is not None:
        from app.domain.consumer_service.grounding import validate_claims

        errors = validate_claims(body, claims, {s.source_id: s for s in sources})
        if errors:
            raise ModelOutputInvalid("自动回复依据核验失败", detail="；".join(errors))
        return
    if not body.strip():
        raise ModelOutputInvalid("自动回复为空")
    forbidden = (
        r"(保证|承诺|一定).{0,20}(退款|到账|发货|解决|赔偿)",
        r"(今天|明天|后天|\d+\s*(小时|天)).{0,12}(到账|发货|退款|解决)",
        r"(确诊|肯定是过敏|孕妇.*安全|孕期.*安全|绝对安全)",
        r"(已为您|已经为您|已经帮您|已帮您).{0,12}(退款|打款|退货|换货|补发|赔付|修改)",
        r"(我会|我这就|我马上|为您|帮您).{0,8}(办理|申请|安排|提交|执行).{0,10}(退款|补发|换货|赔偿|打款)",
        r"(系统提示词|LOREAL_|riskTypes|knowledgeEvidence)",
    )
    if any(re.search(pattern, body) for pattern in forbidden):
        raise ModelOutputInvalid("自动回复需要人工核实")
    amounts = set()
    identifiers = set()
    for order in context.orders:
        identifiers.update(str(value) for value in (order.order_id, order.tracking_no) if value)
        for value in (order.paid_amount_minor, order.unit_price_minor):
            if value is not None:
                amounts.add(round(value / 100, 2))
    for work in context.work_orders:
        identifiers.add(work.work_order_id)
        identifiers.update(
            str(work.detail[key])
            for key in ("originalTrackingNo", "reshipTrackingNo", "trackingNo",
                        "relatedTrackingNo", "refundId", "orderId", "workOrderId")
            if work.detail.get(key)
        )
        value = work.detail.get("refundAmount")
        if value is not None:
            with contextlib.suppress(TypeError, ValueError):
                amounts.add(round(float(value), 2))
    for left, right in re.findall(r"(?:[¥￥]\s*(\d+(?:\.\d+)?))|(?:(\d+(?:\.\d+)?)\s*元)", body):
        if round(float(left or right), 2) not in amounts:
            raise ModelOutputInvalid("回复金额缺少订单或工单依据")
    for number in re.findall(r"(?<![A-Za-z0-9])[A-Za-z]*\d{6,}(?![A-Za-z0-9])", body):
        if not any(number == value for value in identifiers):
            raise ModelOutputInvalid("回复编号缺少关联记录")
    if any(term in body for term in ("已发货", "已经发货", "已签收", "已完成退款", "已到账")):
        source = " ".join(str(order.source_status or "") for order in context.orders)
        source += " " + " ".join(
            json.dumps(w.detail, ensure_ascii=False) for w in context.work_orders
        )
        for term in ("已发货", "已经发货", "已签收", "已完成退款", "已到账"):
            if term in body and term.replace("已经", "已") not in source:
                raise ModelOutputInvalid("回复状态缺少源记录依据")


def _finish_handoff(
    runtime: Any, job_id: str, reason: str, reply: str | None = None,
    expected_input_hash: str | None = None,
) -> None:
    with runtime.new_session() as session:
        locked = session.execute(update(AutoReplyJobRow).where(
            AutoReplyJobRow.job_id == job_id, AutoReplyJobRow.status == "running",
        ).values(updated_at=AutoReplyJobRow.updated_at))
        if locked.rowcount != 1:
            return
        job = session.get(AutoReplyJobRow, job_id)
        if not job or job.status != "running":
            return
        conversation = session.get(ConversationRow, job.conversation_id)
        if not _eligible(conversation, job):
            job.status, job.updated_at = "superseded", utcnow()
        else:
            if remaining_job_seconds(runtime, job) <= 0:
                reason, reply = "reply_timeout", None
            if reply and expected_input_hash:
                from app.domain.consumer_service.workspace import assistant_input_hash

                if assistant_input_hash(session, job.conversation_id) != expected_input_hash:
                    reply = None
            if remaining_job_seconds(runtime, job) <= 0:
                reason, reply = "reply_timeout", None
            try:
                change_mode(
                    session, job.conversation_id, ServiceMode.OPERATOR_ASSISTED,
                    actor="system", reason=reason,
                    expected_mode_revision=job.mode_revision,
                    expected_message_revision=job.message_revision,
                    transition_reply=reply,
                )
                job.status, job.error_code, job.updated_at = "handoff", reason, utcnow()
            except ConflictError:
                job.status, job.updated_at = "superseded", utcnow()
        session.commit()


def process_job(runtime: Any, job_id: str) -> None:
    from app.domain.consumer_service.assistant import ConsumerServiceAssistant
    from app.domain.consumer_service.grounding import record_failure
    from app.repositories.consumer_service import ConsumerServiceRepository

    def still_current():
        with runtime.new_session() as check:
            job = check.get(AutoReplyJobRow, job_id)
            return bool(job and job.status == "running"
                        and _eligible(check.get(ConversationRow, job.conversation_id), job))

    def record_failed_attempt(error):
        with runtime.new_session() as failure_session:
            job = failure_session.get(AutoReplyJobRow, job_id)
            if job:
                record_failure(failure_session, job.conversation_id, error)
                failure_session.commit()

    with runtime.new_session() as session:
        job = session.get(AutoReplyJobRow, job_id)
        if job is None:
            return
        lock_key = f"{runtime.engine.url}:{job.conversation_id}"
    with _registry_lock:
        lock = _locks.setdefault(lock_key, Lock())
    if not lock.acquire(blocking=False):
        return
    try:
        with runtime.new_session() as session:
            job = session.get(AutoReplyJobRow, job_id)
            if job is None or job.status != "queued":
                return
            conversation = session.get(ConversationRow, job.conversation_id)
            if not _eligible(conversation, job):
                job.status, job.updated_at = "superseded", utcnow()
                session.commit()
                return
            trigger = session.get(MessageRow, job.trigger_message_id)
            if trigger is None:
                job.status, job.updated_at = "cancelled", utcnow()
                session.commit()
                return
            job.status, job.updated_at = "running", utcnow()
            job.attempts += 1
            conversation_id = job.conversation_id
            remaining = remaining_job_seconds(runtime, job)
            session.commit()
            context = ConsumerServiceRepository(session).context(conversation_id)
            handoff = _safety_handoff(trigger.body or "")
            attachments = json.loads(trigger.attachments_json or "[]")
        if remaining <= 0:
            _finish_handoff(runtime, job_id, "reply_timeout")
            return
        if handoff:
            _finish_handoff(runtime, job_id, "safety_review")
            return
        if attachments and not runtime.model_provider.supports_vision:
            _finish_handoff(runtime, job_id, "unsupported_image")
            return
        if not runtime.model_provider.available():
            _finish_handoff(runtime, job_id, "model_unavailable")
            return
        try:
            with runtime.new_session() as generation_session:
                assistant = ConsumerServiceAssistant(
                    generation_session,
                    runtime.model_provider,
                    runtime=runtime,
                ).build(conversation_id, automatic=True, still_current=still_current,
                        timeout_seconds=remaining_job_seconds(runtime, job))
                if assistant.is_mock and runtime.settings.run_mode != "mock":
                    raise ModelOutputInvalid("真实接待禁止发送Mock结果")
                reply = next(
                    (r for r in assistant.reply_suggestions if r.style == "recommended"),
                    assistant.reply_suggestions[0],
                )
                body = reply.body
                if assistant.verification_status != "verified":
                    raise ModelOutputInvalid("回复未经独立事实核验")
                validate_auto_reply(body, context, claims=reply.claims,
                                    sources=assistant.grounding_sources)
                if assistant.knowledge_status == "failed":
                    raise ModelOutputInvalid("检索服务异常，转人工核实")
                # Do not keep generation's SQLite transaction while checking for takeover.
                generation_session.commit()
                # Skin photos and unreadable images always need a person, whatever the intent.
                image_review = any(
                    source.kind == "image_observation" and source.fields.get("requiresHumanReview")
                    for source in assistant.grounding_sources
                )
                if assistant.handoff_required and (image_review or assistant.intent not in {
                    "product_question", "order_status", "logistics", "other",
                }):
                    _finish_handoff(runtime, job_id, "model_requested", reply=body,
                                    expected_input_hash=assistant.input_hash)
                    return
        except ProviderTimeout as exc:
            record_failed_attempt(exc)
            _finish_handoff(runtime, job_id, "reply_timeout")
            return
        except ModelOutputInvalid as exc:
            from app.logging_setup import get_logger

            get_logger(__name__).warning(
                "Automatic reply rejected: %s detail=%s", exc.message, exc.detail
            )
            fallback = body if 'body' in locals() else ""
            if fallback:
                _finish_handoff(runtime, job_id, "invalid_reply", reply=fallback)
            else:
                record_failed_attempt(exc)
                _finish_handoff(runtime, job_id, "invalid_reply")
            return
        except Exception as exc:
            record_failed_attempt(exc)
            _finish_handoff(runtime, job_id, "generation_failed")
            return
        with runtime.new_session() as session:
            locked = session.execute(update(AutoReplyJobRow).where(
                AutoReplyJobRow.job_id == job_id, AutoReplyJobRow.status == "running",
            ).values(updated_at=AutoReplyJobRow.updated_at))
            if locked.rowcount != 1:
                return
            job = session.get(AutoReplyJobRow, job_id)
            if job is None or job.status != "running":
                return
            if remaining_job_seconds(runtime, job) <= 0:
                session.rollback()
                _finish_handoff(runtime, job_id, "reply_timeout")
                return
            from app.domain.consumer_service.workspace import assistant_input_hash

            if assistant_input_hash(session, job.conversation_id) != assistant.input_hash:
                if job.attempts < 2:
                    job.status, job.updated_at = "queued", utcnow()
                    session.commit()
                else:
                    session.rollback()
                    _finish_handoff(runtime, job_id, "invalid_reply")
                return
            if remaining_job_seconds(runtime, job) <= 0:
                session.rollback()
                _finish_handoff(runtime, job_id, "reply_timeout")
                return
            # The conditional UPDATE holds the write lock through message insertion.
            claimed = session.execute(
                update(ConversationRow)
                .where(
                    ConversationRow.conversation_id == job.conversation_id,
                    ConversationRow.service_mode == ServiceMode.AUTONOMOUS.value,
                    ConversationRow.mode_revision == job.mode_revision,
                    ConversationRow.message_revision == job.message_revision,
                )
                .values(message_revision=job.message_revision + 1, updated_at=utcnow())
            )
            if claimed.rowcount != 1:
                job.status, job.updated_at = "superseded", utcnow()
                session.commit()
                return
            reply = MessageRow(
                message_id=new_id("msg"),
                conversation_id=job.conversation_id,
                sender_role=SenderRole.ASSISTANT.value,
                body=body,
                client_message_key=f"auto:{job.job_id}",
                applies_to_message_revision=job.message_revision + 1,
                attachments_json="[]",
            )
            session.add(reply)
            session.flush()
            from app.domain.consumer_service.risk_rules import evaluate_risks

            # The reply itself closes a local response-wait signal in this transaction.
            evaluate_risks(session)
            job.status, job.reply_message_id, job.updated_at = "sent", reply.message_id, utcnow()
            AuditRecorder(session).record(
                AuditContext.new_turn(actor_type="agent", conversation_id=job.conversation_id),
                event_type="auto_reply_sent",
                detail={
                    "jobId": job.job_id,
                    "messageId": reply.message_id,
                    "triggerMessageId": job.trigger_message_id,
                    "model": assistant.model_id,
                    "isMock": assistant.is_mock,
                },
            )
            session.commit()
    except Exception:
        _finish_handoff(runtime, job_id, "generation_failed")
    finally:
        lock.release()


async def run_reply_worker(runtime: Any) -> None:
    """Single-process local worker, at most four different conversations at a time."""
    from app.logging_setup import get_logger

    logger = get_logger(__name__)
    with runtime.new_session() as session:
        session.execute(
            update(AutoReplyJobRow)
            .where(AutoReplyJobRow.status == "running")
            .values(status="queued", updated_at=utcnow())
        )
        session.commit()
    active: dict[str, asyncio.Task] = {}
    try:
        while True:
            try:
                await asyncio.to_thread(expire_jobs, runtime)
                for job_id in list(active):
                    if active[job_id].done():
                        active.pop(job_id).result()
                with runtime.new_session() as session:
                    ids = list(
                        session.scalars(
                            select(AutoReplyJobRow.job_id)
                            .where(
                                AutoReplyJobRow.status == "queued",
                            )
                            .order_by(AutoReplyJobRow.created_at)
                            .limit(max(0, 4 - len(active)))
                        )
                    )
                for job_id in ids:
                    if job_id not in active:
                        active[job_id] = asyncio.create_task(
                            asyncio.to_thread(process_job, runtime, job_id)
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Auto reception worker: %s", type(exc).__name__)
            await asyncio.sleep(0.5)
    finally:
        for task in active.values():
            task.cancel()
        await asyncio.gather(*active.values(), return_exceptions=True)


def expire_jobs(runtime: Any) -> None:
    cutoff = utcnow() - timedelta(seconds=runtime.settings.auto_reply_timeout_seconds)
    with runtime.new_session() as session:
        rows = list(
            session.scalars(
                select(AutoReplyJobRow).where(
                    AutoReplyJobRow.status.in_(["queued", "running"]),
                    AutoReplyJobRow.created_at < cutoff,
                )
            )
        )
        for job in rows:
            conversation = session.get(ConversationRow, job.conversation_id)
            if not _eligible(conversation, job):
                job.status, job.updated_at = "superseded", utcnow()
                continue
            try:
                change_mode(
                    session, job.conversation_id, ServiceMode.OPERATOR_ASSISTED,
                    actor="system", reason="reply_timeout",
                    expected_mode_revision=job.mode_revision,
                    expected_message_revision=job.message_revision,
                )
                job.status, job.error_code, job.updated_at = "handoff", "reply_timeout", utcnow()
            except ConflictError:
                job.status, job.updated_at = "superseded", utcnow()
        session.commit()
