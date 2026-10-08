"""客服侧接口（客服工作台）。

归属约束（前端规范第 3、4 节）：只有客服侧才有案件信息、AI 辅助、知识依据、
话术候选与申请审批。客户侧不挂载这些接口。

权限（工程规范第 13.3 节）：这些接口必须由服务端校验角色；
演示角色切换不是生产认证，但客户上下文直接请求必须被拒绝（AC-30）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_context, get_session, require_support
from app.domain.case_state.state_machine import can_transition_case
from app.domain.enums import (
    ServiceRiskLevel,
    ServiceRiskStatus,
    ServiceRiskType,
    ViewRole,
)
from app.errors import ValidationRejected
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.conversation_service import ConversationService
from app.routes.commit import CommitBeforeResponseRoute
from app.runtime import RuntimeContext
from app.schemas.base import ApiModel
from app.schemas.consumer_service import (
    ConsumerServiceAssistantView,
    ConsumerServiceContextView,
    RiskAlertDetailView,
    RiskAlertStatusRequest,
    RiskAlertView,
)
from app.schemas.conversation import (
    CaseView,
    MessageView,
    QueueItem,
    RequestView,
    ReviewRequest,
    SendMessageRequest,
    ServiceModeRequest,
    ServiceModeView,
    SuggestionActionRequest,
    SuggestionSetView,
    SuggestionView,
)

router = APIRouter(
    prefix="/api/support",
    tags=["support"],
    # 事务必须在响应发出**之前**提交，否则「写 200 已返回、紧接着的读看不到」
    # 会真实发生（缺陷第 49 项，原因与验证见 app/routes/commit.py）。
    route_class=CommitBeforeResponseRoute,
)


@router.get("/queue", response_model=list[QueueItem])
async def queue(
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> list[QueueItem]:
    return ConversationService(session).support_queue()


@router.get("/service-queue", response_model=list[QueueItem])
async def service_queue(
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> list[QueueItem]:
    from app.repositories.consumer_service import ConsumerServiceRepository

    return ConsumerServiceRepository(session).queue()


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageView])
async def list_messages(
    conversation_id: str,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> list[MessageView]:
    return ConversationService(session).list_messages(conversation_id)


@router.get(
    "/conversations/{conversation_id}/service-context",
    response_model=ConsumerServiceContextView,
)
async def service_context(
    conversation_id: str,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> ConsumerServiceContextView:
    from app.repositories.consumer_service import ConsumerServiceRepository

    return ConsumerServiceRepository(session).context(conversation_id)


@router.get(
    "/conversations/{conversation_id}/assistant",
    response_model=ConsumerServiceAssistantView | None,
)
async def consumer_service_assistant(
    conversation_id: str,
    session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_support),
) -> ConsumerServiceAssistantView | None:
    from app.domain.consumer_service.assistant import read_assistant

    return read_assistant(session, conversation_id)


@router.get("/risk-alerts", response_model=list[RiskAlertView])
async def list_risk_alerts(
    risk_type: ServiceRiskType | None = None,
    risk_level: ServiceRiskLevel | None = None,
    risk_status: ServiceRiskStatus | None = None,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> list[RiskAlertView]:
    from app.domain.consumer_service.risk import RiskAlertRepository, risk_alert_view

    repository = RiskAlertRepository(session)
    return [
        risk_alert_view(row, session)
        for row in repository.list(
            batch_id=repository.active_batch_id(),
            risk_type=risk_type,
            risk_level=risk_level,
            risk_status=risk_status,
        )
    ]


@router.get("/risk-alerts/{alert_id}", response_model=RiskAlertDetailView)
async def risk_alert_detail(
    alert_id: str,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> RiskAlertDetailView:
    from app.domain.consumer_service.risk import RiskAlertRepository, risk_alert_view
    from app.repositories.consumer_service import ConsumerServiceRepository

    repository = RiskAlertRepository(session)
    alert = repository.get(alert_id)
    return RiskAlertDetailView(
        alert=risk_alert_view(alert, session),
        service_context=ConsumerServiceRepository(session).context(alert.conversation_id),
    )


@router.post("/risk-alerts/{alert_id}/status", response_model=RiskAlertView)
async def update_risk_alert_status(
    alert_id: str,
    payload: RiskAlertStatusRequest,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> RiskAlertView:
    from app.domain.consumer_service.risk import RiskAlertRepository, risk_alert_view

    row = RiskAlertRepository(session).update_status(
        alert_id=alert_id,
        target=payload.status,
        actor=ViewRole.SUPPORT.value,
        note=payload.note,
    )
    return risk_alert_view(row, session)


@router.get("/conversations/{conversation_id}/case", response_model=CaseView | None)
async def case_detail(
    conversation_id: str,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> CaseView | None:
    """案件信息 + 知识依据 + 申请列表。仅客服可见。"""

    return ConversationService(session).case_view(conversation_id, include_evidence=True)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageView)
async def send_operator_message(
    conversation_id: str,
    payload: SendMessageRequest,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> MessageView:
    """客服发送消息。

    托管期间必须先接管再发送（工程规范第 13.2 节）：
    这里校验服务模式，避免「暗中接管」。
    """

    from app.domain.enums import SenderRole, ServiceMode
    from app.errors import ConflictError
    from app.repositories.conversation_repository import ConversationRepository
    from app.repositories.conversation_service import message_view

    service = ConversationService(session)
    conversation = service.get_conversation(conversation_id)

    if ServiceMode(conversation.service_mode) is ServiceMode.AUTONOMOUS:
        raise ConflictError(
            "当前会话处于 AI 托管，客服发送前必须先执行「接管会话」",
            detail="接管与恢复托管是独立操作，不通过发送消息隐式完成",
        )

    repo = ConversationRepository(session)
    row, created = repo.append_message(
        conversation,
        sender_role=SenderRole.OPERATOR,
        body=payload.body,
        client_message_key=payload.client_message_key,
    )
    if created:
        from app.audit.recorder import AuditContext, AuditRecorder, summarize

        AuditRecorder(session).record(
            AuditContext.new_turn(actor_type="operator", conversation_id=conversation_id),
            event_type="operator_message",
            input_text=payload.body,
            detail={
                "messageId": row.message_id,
                "messageRevision": row.applies_to_message_revision,
                "bodySummary": summarize(payload.body, limit=120),
            },
        )
        from app.domain.consumer_service.risk_rules import evaluate_risks

        evaluate_risks(session)
    return message_view(row)


@router.post(
    "/conversations/{conversation_id}/service-mode",
    response_model=ServiceModeView,
)
async def set_service_mode(
    conversation_id: str,
    payload: ServiceModeRequest,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> ServiceModeView:
    """接管会话 / 恢复 AI 托管。两个方向都是独立操作。"""

    from app.domain.consumer_service.auto_reception import change_mode

    return change_mode(session, conversation_id, payload.mode, actor="operator")


@router.post("/requests/{request_id}/review", response_model=RequestView)
async def review_request(
    request_id: str,
    payload: ReviewRequest,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> RequestView:
    """批准 / 拒绝 / 退回补充。

    批准只表示 Demo 内的人工确认，**不代表**真实退款或换货已完成。
    拒绝与退回必须给出原因；旧版本的确认会被拒绝。
    """

    from app.audit.recorder import AuditContext, AuditRecorder
    from app.domain.after_sales.requests import RequestRepository
    from app.repositories.conversation_service import request_view

    repo = RequestRepository(session)
    before = repo.get(request_id)
    repo.review(
        request_id,
        action=payload.action,
        reviewer_role=ViewRole.SUPPORT.value,
        reason=payload.reason,
        reason_text=payload.reason_text,
        expected_revision=payload.expected_revision,
        expected_payload_hash=payload.expected_payload_hash,
    )
    row = repo.get(request_id)

    # 人工确认必须留痕：谁、何时、对哪个版本的申请、做了什么、为什么
    AuditRecorder(session).record(
        AuditContext.new_turn(
            actor_type="operator",
            conversation_id=row.conversation_id,
            case_id=row.case_id,
        ),
        event_type="human_review",
        risk_level="request_creation",
        human_confirmation_status=row.request_status,
        detail={
            "requestId": row.request_id,
            "action": payload.action,
            "fromStatus": before.request_status,
            "toStatus": row.request_status,
            "requestRevision": row.request_revision,
            "payloadHash": row.payload_hash,
            "approvedRevision": row.approved_revision,
            "reviewerRole": row.reviewer_role,
            "reason": row.review_reason,
            "reasonText": row.review_reason_text,
        },
    )
    return request_view(row)


@router.get("/requests/pending", response_model=list[RequestView])
async def pending_requests(
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> list[RequestView]:
    """待人工确认队列。未操作时一直在这里，无超时、无自动升级。"""

    from app.domain.after_sales.requests import RequestRepository
    from app.repositories.conversation_service import request_view

    return [request_view(row) for row in RequestRepository(session).list_pending()]


@router.get("/audit/{conversation_id}")
async def audit_trail(
    conversation_id: str,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> list[dict[str, object]]:
    """案件相关审计轨迹（仅客服）。不返回完整 prompt/output。"""

    from sqlalchemy import select

    from app.domain.case_state.models import AuditEventRow

    rows = list(
        session.execute(
            select(AuditEventRow)
            .where(AuditEventRow.conversation_id == conversation_id)
            .order_by(AuditEventRow.created_at.asc())
        ).scalars()
    )
    return [
        {
            "auditEventId": row.audit_event_id,
            "traceId": row.trace_id,
            "actorType": row.actor_type,
            "eventType": row.event_type,
            "toolName": row.tool_name,
            "toolStatus": row.tool_status,
            "riskLevel": row.risk_level,
            "humanConfirmationStatus": row.human_confirmation_status,
            "knowledgeSnapshotVersion": row.knowledge_snapshot_version,
            "modelName": row.model_name,
            "promptVersion": row.prompt_version,
            "createdAt": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/health/echo")
async def support_echo(
    _role: ViewRole = Depends(require_support),
    context: RuntimeContext = Depends(get_context),
) -> dict[str, object]:
    """客服侧连通性检查，同时暴露契约版本便于前端对齐。"""

    return {
        "ok": True,
        "viewRole": ViewRole.SUPPORT.value,
        "contractVersion": context.settings.contract_version,
        "runMode": context.settings.run_mode,
        "visionConfigured": context.model_provider.supports_vision,
    }


# --------------------------------------------------------------- AI 话术候选


def _suggestion_view(item: Any, *, current_revision: int) -> SuggestionView:
    from app.domain.agent.suggestions import VARIANT_LABELS

    return SuggestionView(
        suggestion_id=item.suggestion_id,
        conversation_id=item.conversation_id,
        message_revision=item.message_revision,
        variant=item.variant,
        variant_label=VARIANT_LABELS.get(item.variant, item.variant),
        body=item.body,
        is_mock=item.is_mock,
        expires=item.message_revision != current_revision,
    )


@router.get(
    "/conversations/{conversation_id}/suggestions",
    response_model=SuggestionSetView | None,
)
async def get_suggestions(
    conversation_id: str,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> SuggestionSetView | None:
    """读取当前候选。新客户消息到达后 `expires=true`，不得静默发送。"""

    from app.domain.agent.suggestions import list_suggestions

    result = list_suggestions(session, conversation_id)
    if result is None:
        return None
    conversation = ConversationService(session).get_conversation(conversation_id)
    return SuggestionSetView(
        conversation_id=conversation_id,
        message_revision=result.message_revision,
        current_revision=conversation.message_revision,
        expires=result.expires,
        is_mock=result.is_mock,
        model_id=result.model_id,
        items=[
            _suggestion_view(item, current_revision=conversation.message_revision)
            for item in result.items
        ],
    )


@router.post(
    "/conversations/{conversation_id}/suggestions/generate",
    response_model=SuggestionSetView,
)
async def generate_suggestions(
    conversation_id: str,
    session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_support),
) -> SuggestionSetView:
    """按当前上下文生成「推荐 / 简洁 / 安抚」三种措辞。

    候选必须来自真实模型；模型不可用时返回明确错误，不提供预设文案兜底。
    """

    from app.audit.recorder import AuditContext, AuditRecorder
    from app.domain.agent.suggestions import SUGGESTION_PROMPT_VERSION, build_suggestion
    from app.domain.case_state.models import CaseRow

    service = ConversationService(session)
    conversation = service.get_conversation(conversation_id)
    case_view = service.case_view(conversation_id, include_evidence=True)

    excerpts = [item.quoted_excerpt for item in (case_view.evidence if case_view else [])]
    case = (
        session.execute(select(CaseRow).where(CaseRow.conversation_id == conversation_id))
        .scalars()
        .first()
    )

    result = build_suggestion(
        session,
        conversation=conversation,
        case=case,
        provider=context.model_provider,
        knowledge_excerpts=excerpts,
    )

    AuditRecorder(session).record(
        AuditContext.new_turn(
            actor_type="agent",
            conversation_id=conversation_id,
            case_id=case.case_id if case else None,
            model_name=result.model_id,
            prompt_version=SUGGESTION_PROMPT_VERSION,
        ),
        event_type="suggestion_generated",
        risk_level="read_only",
        detail={
            "messageRevision": result.message_revision,
            "variants": [item.variant for item in result.items],
            "isMock": result.is_mock,
        },
    )

    return SuggestionSetView(
        conversation_id=conversation_id,
        message_revision=result.message_revision,
        current_revision=conversation.message_revision,
        expires=False,
        is_mock=result.is_mock,
        model_id=result.model_id,
        items=[
            _suggestion_view(item, current_revision=conversation.message_revision)
            for item in result.items
        ],
    )


@router.post(
    "/conversations/{conversation_id}/suggestions/action",
    response_model=SuggestionView,
)
async def suggestion_action(
    conversation_id: str,
    payload: SuggestionActionRequest,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> SuggestionView:
    """采用或忽略候选。

    **采用只写入客服草稿，不发送、不审批、不接管**；发送仍是独立动作。
    """

    from app.audit.recorder import AuditContext, AuditRecorder
    from app.domain.agent.suggestions import mark_action

    row = mark_action(
        session, conversation_id=conversation_id, variant=payload.variant, action=payload.action
    )
    conversation = ConversationService(session).get_conversation(conversation_id)

    AuditRecorder(session).record(
        AuditContext.new_turn(actor_type="operator", conversation_id=conversation_id),
        event_type="suggestion_action",
        human_confirmation_status="not_required",
        detail={
            "variant": payload.variant,
            "action": payload.action,
            "messageRevision": row.message_revision,
            "note": "采用不等于发送" if payload.action == "adopt" else "已忽略候选",
        },
    )
    return _suggestion_view(row, current_revision=conversation.message_revision)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation_support(
    conversation_id: str,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_support),
) -> dict[str, Any]:
    """客服侧删除会话（清理演示数据用）。与客户侧走同一条仓储逻辑。"""

    from app.audit.recorder import AuditContext, AuditRecorder
    from app.repositories.conversation_repository import ConversationRepository

    repo = ConversationRepository(session)
    counts = repo.delete_conversation(conversation_id)
    AuditRecorder(session).record(
        AuditContext.new_turn(actor_type="operator", conversation_id=conversation_id),
        event_type="conversation_deleted",
        detail={"deleted": counts, "note": "审计保留，仅删除业务数据"},
    )
    session.flush()
    return {"conversationId": conversation_id, "deleted": counts}


class CloseConversationRequest(ApiModel):
    reason: str = ""


class CloseConversationView(ApiModel):
    conversation_id: str
    case_id: str
    case_status: str
    rating_status: str
    message: str


@router.post("/conversations/{conversation_id}/close", response_model=CloseConversationView)
async def close_conversation(
    conversation_id: str,
    payload: CloseConversationRequest | None = None,
    session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_support),
) -> CloseConversationView:
    """结束服务并开放评价入口。

    为什么把「结束」和「请求评价」放在一起：PRD 5.2 规定评价在**服务结束时**发起，
    分成两步会留下「关了但评价入口没开」的中间态，客户页面上什么都看不到。
    """

    from app.audit.recorder import AuditContext, AuditRecorder
    from app.domain.case_state.state_machine import can_transition_stage
    from app.domain.enums import CaseStatus, ConversationStage
    from app.errors import NotFoundError

    reason = (payload.reason if payload else "") or "客服结束服务"

    repo = ConversationRepository(session)
    case_row = repo.get_case_by_conversation(conversation_id)
    if case_row is None:
        raise NotFoundError("该会话尚未创建案件，无法结束服务")

    # 已经是 closed：幂等返回，不重复写审计、不重复请求评价
    current = CaseStatus(case_row.case_status)
    if current is CaseStatus.CLOSED:
        return CloseConversationView(
            conversation_id=conversation_id,
            case_id=case_row.case_id,
            case_status=CaseStatus.CLOSED.value,
            rating_status=str(case_row.rating_status),
            message="该会话已结束（重复操作，未重复处理）",
        )

    # 状态转换必须先过状态机：`closed` 是终态，非法转换要如实拒绝而不是硬写
    transition = can_transition_case(current, CaseStatus.CLOSED)
    if not transition.allowed:
        raise ValidationRejected(transition.reason)

    # 会话阶段尽力推进到「收尾」：阶段机不允许时保持原阶段，不静默改写成 CLOSED
    stage_before = ConversationStage(case_row.conversation_stage)
    stage_moved = False
    if can_transition_stage(stage_before, ConversationStage.CLOSURE).allowed:
        stage_moved = repo.set_stage(case_row, ConversationStage.CLOSURE)

    repo.set_case_status(case_row, CaseStatus.CLOSED, actor_type="operator")

    AuditRecorder(session).record(
        AuditContext.new_turn(
            actor_type="operator", conversation_id=conversation_id, case_id=case_row.case_id
        ),
        event_type="service_closed",
        detail={
            "reason": reason,
            "stage_before": stage_before.value,
            "stage_moved_to_closure": stage_moved,
        },
    )

    # 请求评价：是否允许由状态机判定（有待确认申请或草稿时不允许）
    gateway = context.build_gateway(session)
    rating = gateway.invoke(
        "record_rating",
        {"caseId": case_row.case_id, "action": "request"},
        as_agent=False,
    )
    rating_status = rating.data.get("ratingStatus") if rating.ok else case_row.rating_status
    message = (
        "服务已结束，客户侧可以评价"
        if rating.ok
        else f"服务已结束，但评价入口未开放：{rating.message}"
    )
    session.flush()
    return CloseConversationView(
        conversation_id=conversation_id,
        case_id=case_row.case_id,
        case_status=CaseStatus.CLOSED.value,
        rating_status=str(rating_status),
        message=message,
    )
