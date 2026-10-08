"""Evidence-qualified service gaps; findings never execute work or close a risk."""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.consumer_service.grounding import (
    collect_sources,
    source_hash,
    usage_for,
    validate_sources_budget,
)
from app.domain.consumer_service.models import AssistantRunRow, ServiceBreakpointAssessmentRow
from app.errors import ModelOutputInvalid, NotFoundError
from app.integrations.model_provider import ChatMessage
from app.schemas.grounding import GroundingSource, WorkflowStep
from app.schemas.service_breakpoints import (
    BreakpointCandidate,
    BreakpointEvidence,
    ServiceBreakpointAssessmentView,
    ServiceBreakpointView,
)

VERSION = "service-breakpoints-v1.1"
KIND_LABELS = {
    "repeated_question": "重复咨询未解决",
    "unmet_promise": "承诺兑现待核实",
    "resolution_mismatch": "完结后诉求未解决",
}
RECOMMENDATIONS = {
    "repeated_question": "核对同一诉求的历史答复和实际进展，给出明确下一步",
    "unmet_promise": "核对承诺内容及兑现记录，确认消费者仍待解决的事项",
    "resolution_mismatch": "以消费者反馈核验解决结果，不仅依据工单完结",
}
PROMISE_SPAN = re.compile(r"(?<!\d)([1-9]\d{0,2})\s*(小时|天)(?:内|之内|以内)")
PROMISE_DATE = re.compile(r"(?<!\d)(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})(?:日|号)?")
EXPLICIT_ORDER = re.compile(r"订单(?:号)?[：:\s]*([A-Za-z]*\d{6,})")


class BreakpointOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service_breakpoints: list[BreakpointCandidate] = Field(max_length=3)


class BreakpointVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supported: bool
    issues: list[str] = Field(default_factory=list, max_length=8)


BREAKPOINT_ONLY_PROMPT = """你只分析服务断点，不生成客服回复，不生成memory、intent或任何其他字段。
只输出JSON：{"service_breakpoints":[...]}。
repeated_question：同一诉求在观察窗口内至少两条不同消费者消息，且当前仍未解决。
unmet_promise：实际客服/AI发言有明确小时/天/日期承诺，截止后消费者仍反馈同一问题。
resolution_mismatch：业务记录完结后，消费者对同一事项仍反馈未解决。
没有可靠断点必须输出空数组。每项至少引用两条连续原文，并包含当前会话最新消费者消息。
不要把不同话题、感谢、重复发送或普通补充信息当作断点；不要执行风险关闭或售后动作。
状态来源只能是订单、源工单或本地跟进，AI发言只证明说过的话。
完整结构由用户输入中的service_breakpoints字段说明。"""

BREAKPOINT_VERIFY_PROMPT = """GROUNDING_REVIEW_V1
你是服务断点的独立核验步骤，不负责生成回复。
逐项核验service_breakpoints的同一诉求、角色、时间、订单/工单关联及逐字证据。
没有明确同一问题、当前最新消费者反馈、有效期限或完结后时间关系时，要求删除候选。
只返回JSON：{"supported":true或false,"issues":["具体问题"]}。
这次分析独立于客服回复；不要因为回复、claims或商品资料失败而否定服务断点。"""


def moment(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Imported workbook timestamps are UTC+8; live message timestamps carry UTC.
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone(timedelta(hours=8)))
    return result.astimezone(UTC)


def promise_deadline(source: GroundingSource, quote: str) -> datetime | None:
    base = moment(source.occurred_at)
    durations, dates = PROMISE_SPAN.findall(quote), PROMISE_DATE.findall(quote)
    if base is None or len(durations) + len(dates) != 1:
        return None
    if durations:
        amount, unit = durations[0]
        hours = int(amount) * (24 if unit == "天" else 1)
        return base + timedelta(hours=hours) if hours <= 720 else None
    try:
        year, month, day = (int(value) for value in dates[0])
        return datetime(year, month, day, 23, 59, 59,
                        tzinfo=timezone(timedelta(hours=8))).astimezone(UTC)
    except ValueError:
        return None


def additional_statements(messages: list[Any], sources: list[GroundingSource]) -> list[GroundingSource]:
    known = {s.source_id for s in sources}
    result = []
    for message in messages[-48:]:
        ref = f"message:{message.conversation_id}:{message.message_id}"
        if message.sender_role.value != "assistant" or not message.body or ref in known:
            continue
        result.append(GroundingSource(
            source_id=ref, kind="staff_message", subject_id=message.conversation_id,
            label="AI接待发言", text=message.body, occurred_at=message.created_at,
            fields={"speaker": "assistant", "authority": "statement_only"},
        ))
    return result


def qualify_findings(
    candidates: list[BreakpointCandidate], sources: list[GroundingSource],
    statements: list[GroundingSource], context: Any, *, repeat_hours: int = 72,
) -> tuple[list[ServiceBreakpointView], list[str]]:
    catalog = {s.source_id: s for s in [*sources, *statements]}
    current = [s for s in sources if s.kind == "customer_message"
               and s.subject_id == context.conversation_id]
    if not current:
        return [], ["服务断点需要当前消费者原文"] if candidates else []
    latest = current[-1]
    findings, issues = [], []
    for candidate in candidates:
        local_issues = []
        cited = []
        for citation in candidate.evidence:
            source = catalog.get(citation.source_ref)
            if source is None or citation.quote not in source.text or source.kind in {"knowledge", "image_observation"}:
                local_issues.append("服务断点证据必须引用服务目录中的连续原文")
            else:
                cited.append((source, citation.quote))
        customers = {s.source_id: s for s, _ in cited if s.kind == "customer_message"}
        if latest.source_id not in customers:
            local_issues.append("服务断点必须包含当前会话最新消费者消息")
        state = catalog.get(candidate.state_ref) if candidate.state_ref else None
        if candidate.state_ref and (state is None or state.kind not in {"order", "work_order", "followup"}
                                    or candidate.state_ref not in {s.source_id for s, _ in cited}):
            local_issues.append("业务状态必须来自已引用的订单、工单或本地跟进记录")
        state_order = state.fields.get("orderId") if state else None
        order_id = candidate.order_id or state_order
        allowed = {context.conversation_id}
        known_orders = {o.order_id for o in context.orders} | {
            w.order_id for w in context.work_orders if w.order_id
        }
        if order_id:
            if order_id not in known_orders:
                local_issues.append("服务断点不能关联当前服务范围之外的订单")
            else:
                allowed.update(o.conversation_id for o in context.orders if o.order_id == order_id)
                allowed.update(w.conversation_id for w in context.work_orders if w.order_id == order_id)
            if state_order and order_id != state_order:
                local_issues.append("服务断点引用了另一笔订单的状态")
            if not any(s.fields.get("orderId") == order_id or order_id in quote for s, quote in cited):
                local_issues.append("关联订单必须出现在所引用的证据中")
        if any(s.kind in {"customer_message", "staff_message"} and s.subject_id not in allowed
               for s, _ in cited):
            local_issues.append("不同会话只能通过明确的同一订单证据关联")
        mentioned_orders = {order for s, quote in cited if s.kind == "customer_message"
                            for order in EXPLICIT_ORDER.findall(quote)}
        if len(mentioned_orders) > 1 or (order_id and mentioned_orders - {order_id}):
            local_issues.append("服务断点不能合并不同订单的消费者诉求")
        state_ticket = state.fields.get("workOrderId") or state.fields.get("ticketId") if state else None
        ticket_id = candidate.work_order_id or state_ticket
        if candidate.work_order_id and candidate.work_order_id != state_ticket:
            local_issues.append("关联工单必须由所引用的业务状态记录证明")
        times = [moment(s.occurred_at) for s in customers.values()]
        latest_at = moment(latest.occurred_at)
        if latest_at is None or any(value is None for value in times):
            local_issues.append("服务断点的消费者消息缺少有效时间")
        due = None
        if candidate.kind == "repeated_question":
            if len(customers) < 2:
                local_issues.append("重复咨询必须引用至少两条不同消费者消息")
            elif all(times) and max(times) - min(times) > timedelta(hours=repeat_hours):
                local_issues.append(f"重复咨询证据超出{repeat_hours}小时观察窗口")
        elif candidate.kind == "unmet_promise":
            promise = catalog.get(candidate.promise_ref) if candidate.promise_ref else None
            quote = next((quote for s, quote in cited if s.source_id == candidate.promise_ref), None)
            if promise is None or promise.kind != "staff_message" or quote is None:
                local_issues.append("承诺必须引用实际客服或AI接待发言")
            else:
                due = promise_deadline(promise, quote)
                if due is None:
                    local_issues.append("承诺原文没有可唯一确定的期限，不能编造截止时间")
                elif latest_at is not None and latest_at <= due:
                    local_issues.append("消费者反馈不晚于承诺期限，不能判断承诺到期")
        elif candidate.kind == "resolution_mismatch":
            completed = state is not None and (
                (state.kind == "work_order" and state.fields.get("sourceStatus") in {"已完结", "已完成", "已处理"})
                or (state.kind == "followup" and state.fields.get("localStatus") == "resolved")
            )
            completed_at = moment(state.fields.get("completedAt")) if completed and state.kind == "work_order" else (
                moment(state.occurred_at) if completed else None
            )
            if not completed or completed_at is None:
                local_issues.append("完结后诉求需要可证明完结状态和时间的工单记录")
            elif latest_at is not None and latest_at <= completed_at:
                local_issues.append("消费者反馈发生在完结之前，不能判断完结后仍未解决")
        if local_issues:
            issues.extend(local_issues)
            continue
        findings.append(ServiceBreakpointView(
            kind=candidate.kind, kind_label=KIND_LABELS[candidate.kind],
            topic=candidate.topic, reason=candidate.reason,
            evidence=[BreakpointEvidence(
                source_ref=s.source_id, quote=quote, kind=s.kind, label=s.label,
                occurred_at=s.occurred_at,
                conversation_id=s.subject_id if s.kind in {"customer_message", "staff_message"} else None,
            ) for s, quote in cited],
            order_id=order_id, work_order_id=ticket_id,
            detected_at=latest_at.isoformat(), promise_due_at=due.isoformat() if due else None,
            recommended_action=RECOMMENDATIONS[candidate.kind],
        ))
    return findings, list(dict.fromkeys(issues))


def analyze_service_breakpoints(
    session: Session, provider: Any, runtime: Any, conversation_id: str,
) -> ServiceBreakpointAssessmentView:
    """Analyze service gaps without generating or validating a customer reply."""
    from app.domain.consumer_service.grounded_workflow import SERVICE_CAPABILITIES
    from app.domain.consumer_service.workspace import assistant_input_hash, conversation_messages
    from app.repositories.consumer_service import ConsumerServiceRepository

    context = ConsumerServiceRepository(session).context(conversation_id)
    messages = conversation_messages(session, conversation_id)
    sources = collect_sources(session, conversation_id, context)
    statements = additional_statements(messages, sources)
    validate_sources_budget([*sources, *statements])
    latest = next(
        (message.body for message in reversed(messages)
         if message.sender_role.value == "customer" and message.body),
        "",
    )
    if not latest:
        raise NotFoundError("当前会话没有消费者文字消息")

    source_catalog = [source.dump() for source in [*sources, *statements]]
    input_hash = assistant_input_hash(session, conversation_id, sources=sources)
    service_rules = {"repeatWindowHours": runtime.settings.risk_repeat_contact_hours}
    calls: list[dict[str, Any]] = []
    steps: list[WorkflowStep] = []
    issues: list[str] = []
    previous: dict[str, Any] | None = None
    findings: list[ServiceBreakpointView] | None = None

    def complete(stage: str, prompt: str, payload: dict[str, Any], max_tokens: int):
        started = time.perf_counter()
        result = provider.complete(
            [
                ChatMessage(role="system", content=prompt),
                ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ],
            temperature=0, max_tokens=max_tokens, json_mode=True,
            timeout_seconds=runtime.settings.auto_reply_timeout_seconds,
        )
        calls.append({
            "stage": stage, "model": result.model, "isMock": result.is_mock,
            "promptTokens": result.prompt_tokens, "completionTokens": result.completion_tokens,
            "latencySeconds": result.latency_seconds,
            "inputCharacters": sum(len(message.content) for message in [
                ChatMessage(role="system", content=prompt),
                ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ]),
        })
        return result, round((time.perf_counter() - started) * 1000)

    for attempt in range(1, 3):
        payload = {
            "conversationId": conversation_id,
            "latestCustomerMessage": latest,
            "sourceCatalog": source_catalog,
            "serviceStatements": [source.dump() for source in statements],
            "recentConversation": [
                {"role": message.sender_role.value, "body": message.body}
                for message in messages[-48:]
                if message.body and message.sender_role.value != "system"
            ],
            "serviceCapabilities": SERVICE_CAPABILITIES,
            "serviceGapRules": service_rules,
            "service_breakpoints": {"schema": BreakpointOutput.model_json_schema()},
            "previousDraft": previous,
            "repairIssues": issues,
        }
        try:
            result, duration = complete(
                "breakpoint_draft",
                BREAKPOINT_ONLY_PROMPT,
                payload, 1800,
            )
            raw = json.loads(result.text)
            if not isinstance(raw, dict):
                raise ValueError("断点输出不是JSON对象")
            previous = raw
            candidates = BreakpointOutput.model_validate({
                key: raw[key] for key in ("service_breakpoints",) if key in raw
            })
            findings, issues = qualify_findings(
                candidates.service_breakpoints, sources, statements, context,
                repeat_hours=runtime.settings.risk_repeat_contact_hours,
            )
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            findings = None
            issues = [f"断点输出契约无效：{type(exc).__name__}"]
            duration = 0
        steps.append(WorkflowStep(
            name="断点起草", status="needs_repair" if issues else "passed",
            duration_ms=duration, attempt=attempt, issues=issues[:8],
        ))
        if issues:
            if attempt == 2:
                break
            continue
        # An explicit, valid empty result makes no positive claim to verify.
        if not findings:
            break

        verify_payload = {
            "sourceCatalog": source_catalog,
            "serviceStatements": [source.dump() for source in statements],
            "latestCustomerMessage": latest,
            "draft": {"service_breakpoints": [
                finding.dump() for finding in findings or []
            ]},
            "serviceGapRules": service_rules,
        }
        verify_result, verify_duration = complete(
            "breakpoint_verify", BREAKPOINT_VERIFY_PROMPT, verify_payload, 700,
        )
        try:
            verdict = BreakpointVerification.model_validate_json(verify_result.text)
            issues = (verdict.issues or ["服务断点证据未获核验支持"]) if not verdict.supported else []
        except (ValidationError, ValueError) as exc:
            issues = [f"断点核验输出无效：{type(exc).__name__}"]
        steps.append(WorkflowStep(
            name="断点独立核验", status="needs_repair" if issues else "passed",
            duration_ms=verify_duration, attempt=attempt, issues=issues[:8],
        ))
        if not issues:
            break

    if issues or findings is None:
        error = ModelOutputInvalid("服务断点分析未通过", detail="；".join(issues)[:500])
        error.workflow_calls = calls
        error.workflow_input_hash = input_hash
        error.workflow_steps = [step.dump() for step in steps]
        error.workflow_issues = issues[:8]
        raise error

    run_id = f"run-{uuid.uuid4().hex[:16]}"
    usage = usage_for(calls)
    session.add(AssistantRunRow(
        run_id=run_id, conversation_id=conversation_id, input_hash=input_hash,
        model_id=calls[-1]["model"], is_mock=any(call["isMock"] for call in calls),
        status="verified", trace_json=json.dumps([step.dump() for step in steps], ensure_ascii=False),
        usage_json=json.dumps(usage),
    ))
    session.flush()
    save_assessment(session, conversation_id, context.batch_id, run_id, sources, findings)
    from app.domain.consumer_service.risk_rules import evaluate_risks

    evaluate_risks(session, batch_id=context.batch_id)
    session.flush()
    return read_assessment(session, conversation_id)


def save_assessment(
    session: Session, conversation_id: str, batch_id: str, run_id: str, sources: list[GroundingSource],
    findings: list[ServiceBreakpointView] | None,
) -> None:
    if findings is None:
        return
    row = session.get(ServiceBreakpointAssessmentRow, conversation_id)
    if row is None:
        row = ServiceBreakpointAssessmentRow(conversation_id=conversation_id, revision=0)
        session.add(row)
    row.assessment_id = run_id
    row.batch_id, row.analysis_version = batch_id, VERSION
    row.source_hash = source_hash([s for s in sources if s.kind != "knowledge"])
    row.findings_json = json.dumps([finding.dump() for finding in findings], ensure_ascii=False)
    row.revision += 1
    row.updated_at = datetime.now(UTC)
    session.flush()


def read_assessment(session: Session, conversation_id: str) -> ServiceBreakpointAssessmentView:
    from app.domain.consumer_service.workspace import active_batch

    row = session.get(ServiceBreakpointAssessmentRow, conversation_id)
    if row is None or row.batch_id != active_batch(session):
        return ServiceBreakpointAssessmentView(conversation_id=conversation_id)
    try:
        stale = row.analysis_version != VERSION or row.source_hash != source_hash(collect_sources(session, conversation_id))
    except NotFoundError:
        stale = True
    run = session.get(AssistantRunRow, row.assessment_id)
    return ServiceBreakpointAssessmentView(
        conversation_id=conversation_id, assessment_id=row.assessment_id,
        analyzed=True, stale=stale, revision=row.revision,
        findings=[ServiceBreakpointView.model_validate(f) for f in json.loads(row.findings_json)],
        model_id=run.model_id if run else None, is_mock=run.is_mock if run else False,
        updated_at=row.updated_at.replace(tzinfo=UTC).isoformat(),
        workflow_steps=[WorkflowStep.model_validate(s) for s in json.loads(run.trace_json)] if run else [],
        model_usage=json.loads(run.usage_json) if run else {},
    )


def assessment_signals(session: Session, batch_id: str):
    from app.domain.consumer_service.risk_rules import RiskSignal, utc
    from app.domain.enums import ServiceRiskLevel, ServiceRiskType
    from app.repositories.consumer_service import ConsumerServiceRepository
    from app.schemas.service_desk import RiskEvidenceView

    result = []
    for row in session.scalars(select(ServiceBreakpointAssessmentRow).where(
        ServiceBreakpointAssessmentRow.batch_id == batch_id,
    )):
        view = read_assessment(session, row.conversation_id)
        if not view.findings:
            continue
        try:
            buyer = ConsumerServiceRepository(session).context(row.conversation_id).buyer_alias
        except NotFoundError:
            buyer = row.conversation_id
        evidence = {e.source_ref: RiskEvidenceView(
            ref=e.source_ref, kind=e.kind, label=e.label, body=e.quote, occurred_at=e.occurred_at,
            conversation_id=e.conversation_id,
        ) for f in view.findings for e in f.evidence}
        result.append(RiskSignal(
            row.conversation_id, buyer, ServiceRiskType.SERVICE_BREAKPOINT, ServiceRiskLevel.MEDIUM,
            "；".join(f"{f.kind_label}：{f.reason}" for f in view.findings),
            max(utc(f.detected_at) for f in view.findings), list(evidence.values()),
            sorted({f.order_id for f in view.findings if f.order_id}),
            sorted({f.work_order_id for f in view.findings if f.work_order_id}),
            conditions={"basis": "verified_service_breakpoints", "analysisVersion": VERSION,
                        "analysisStale": view.stale, "assessmentId": row.assessment_id,
                        "breakpointKinds": sorted({f.kind for f in view.findings})},
        ))
    return result
