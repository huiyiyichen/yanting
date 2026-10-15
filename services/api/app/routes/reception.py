from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import Field
from sqlalchemy.orm import Session

from app.deps import get_context, get_session, require_support
from app.domain.consumer_service.cited_text import ReplyStyle
from app.domain.consumer_service.consumer_profile import ConsumerProfileView
from app.domain.consumer_service.draft_review import DraftFinding
from app.domain.consumer_service.product_cards import DeskProductCardView
from app.domain.consumer_service.rewrite import RewriteRequest, RewriteView
from app.domain.consumer_service.workspace import (
    conversation_messages,
    ensure_local_conversation,
    list_source_work_orders,
    mark_seen,
    reception_snapshot,
    send_operator,
)
from app.routes.commit import CommitBeforeResponseRoute
from app.runtime import RuntimeContext
from app.schemas.base import ApiModel
from app.schemas.consumer_service import (
    AssistantActionRequest,
    ConsumerServiceAssistantView,
    ReceptionSnapshotView,
    ServiceWorkOrderView,
)
from app.schemas.conversation import (
    AttachmentView,
    MessageView,
    SendMessageRequest,
    ServiceModeRequest,
    ServiceModeView,
)
from app.schemas.grounding import ServiceMemoryView

router = APIRouter(
    prefix="/api/support/reception",
    tags=["reception"],
    route_class=CommitBeforeResponseRoute,
    dependencies=[Depends(require_support)],
)


class SeenRequest(ApiModel):
    revision: int = Field(ge=0)


@router.get("/queue", response_model=ReceptionSnapshotView)
def queue(session: Session = Depends(get_session)):
    return reception_snapshot(session)


@router.get("/{conversation_id}/messages", response_model=list[MessageView])
def messages(conversation_id: str, session: Session = Depends(get_session)):
    return conversation_messages(session, conversation_id)


@router.post("/{conversation_id}/messages", response_model=MessageView)
def send(
    conversation_id: str, payload: SendMessageRequest, session: Session = Depends(get_session)
):
    return send_operator(
        session, conversation_id, payload.body, payload.client_message_key,
        payload.attachment_ids,
    )


@router.post("/{conversation_id}/attachments", response_model=AttachmentView)
async def upload_attachment(
    conversation_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
) -> AttachmentView:
    from app.repositories.attachment_service import validate_and_store_image
    from app.repositories.conversation_repository import ConversationRepository

    ensure_local_conversation(session, conversation_id)
    stored = validate_and_store_image(
        data=await file.read(), declared_mime=file.content_type,
        settings=context.settings, conversation_id=conversation_id,
    )
    row = ConversationRepository(session).add_attachment(
        conversation_id=conversation_id, message_id=None,
        mime_type=stored.mime_type, byte_size=stored.byte_size,
        stored_path=stored.stored_path, sha256=stored.sha256,
        width=stored.width, height=stored.height,
    )
    return AttachmentView(
        attachment_id=row.attachment_id, conversation_id=row.conversation_id,
        message_id=row.message_id, mime_type=row.mime_type, byte_size=row.byte_size,
        width=row.width, height=row.height, sha256=row.sha256,
        created_at=row.created_at.isoformat(),
    )


@router.post("/{conversation_id}/seen")
def seen(conversation_id: str, payload: SeenRequest, session: Session = Depends(get_session)):
    mark_seen(session, conversation_id, payload.revision)
    return {"ok": True}


@router.post("/{conversation_id}/assistant", response_model=ConsumerServiceAssistantView)
def generate(
    conversation_id: str,
    style: ReplyStyle | None = None,
    session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
):
    """生成接待辅助；带 style 时只替换该风格，其余风格保留上次已核验内容。"""
    from app.domain.consumer_service.assistant import ConsumerServiceAssistant
    from app.domain.consumer_service.grounding import record_failure
    from app.errors import YantingError

    try:
        return ConsumerServiceAssistant(session, context.model_provider, runtime=context).build(
            conversation_id, only_style=style,
        )
    except YantingError as exc:
        session.rollback()
        record_failure(session, conversation_id, exc)
        session.commit()
        raise


@router.get("/{conversation_id}/memory", response_model=ServiceMemoryView)
def service_memory(conversation_id: str, session: Session = Depends(get_session)):
    from app.domain.consumer_service.grounding import memory_view

    return memory_view(session, conversation_id)


@router.post("/{conversation_id}/suggestion-action")
def suggestion_action(
    conversation_id: str,
    payload: AssistantActionRequest,
    session: Session = Depends(get_session),
):
    from app.domain.consumer_service.assistant import record_suggestion_action

    return record_suggestion_action(session, conversation_id, payload)


@router.get("/work-orders/all", response_model=list[ServiceWorkOrderView])
def work_orders(session: Session = Depends(get_session)):
    return list_source_work_orders(session)


@router.post("/{conversation_id}/service-mode", response_model=ServiceModeView)
def set_mode(
    conversation_id: str, payload: ServiceModeRequest, session: Session = Depends(get_session),
):
    from app.domain.consumer_service.auto_reception import change_mode

    return change_mode(session, conversation_id, payload.mode, actor="operator")


@router.get("/{conversation_id}/product-card", response_model=DeskProductCardView | None)
def product_card(conversation_id: str, session: Session = Depends(get_session)):
    """聊天区顶部商品卡：最新商品卡消息 → 本会话关联订单 → 无则为空。"""
    from app.domain.consumer_service.product_cards import desk_card

    return desk_card(session, conversation_id)


@router.get("/{conversation_id}/profile", response_model=ConsumerProfileView)
def consumer_profile(conversation_id: str, session: Session = Depends(get_session)):
    """画像卡：只读聚合聊天、订单、工单与服务记忆，不调用模型。"""
    from app.domain.consumer_service.consumer_profile import build_consumer_profile
    from app.errors import NotFoundError

    profile = build_consumer_profile(session, conversation_id)
    if profile is None:
        raise NotFoundError(f"会话不存在：{conversation_id}")
    return profile


class DraftReviewRequest(ApiModel):
    body: str = Field(max_length=2000)


class DraftReviewView(ApiModel):
    findings: list[DraftFinding]


@router.post("/{conversation_id}/draft-review", response_model=DraftReviewView)
def draft_review(conversation_id: str, payload: DraftReviewRequest, session: Session = Depends(get_session)):
    """发送前质检：纯规则提示，不阻断发送，不调用模型；每次结果写审计。"""
    from app.audit.recorder import AuditContext, AuditRecorder
    from app.domain.consumer_service.draft_review import review_conversation_draft

    findings = review_conversation_draft(session, conversation_id, payload.body) if payload.body.strip() else []
    AuditRecorder(session).record(
        AuditContext.new_turn(actor_type="support", conversation_id=conversation_id),
        event_type="draft_review", input_text=payload.body,
        detail={"findings": [item.model_dump(by_alias=True) for item in findings]},
    )
    return DraftReviewView(findings=findings)


@router.post("/{conversation_id}/assistant/rewrite", response_model=RewriteView)
def rewrite_suggestion(
    conversation_id: str, payload: RewriteRequest,
    session: Session = Depends(get_session), context: RuntimeContext = Depends(get_context),
):
    """改写回复建议：快速模型生成，程序校验事实保真；未通过返回 422 并保留原文。"""
    from app.audit.recorder import AuditContext, AuditRecorder
    from app.domain.consumer_service.assistant import read_assistant
    from app.domain.consumer_service.rewrite import INSTRUCTIONS, rewrite_issues, rewrite_reply
    from app.errors import ConflictError, ValidationRejected

    if payload.instruction not in INSTRUCTIONS:
        raise ValidationRejected("不支持的改写方式")
    view = read_assistant(session, conversation_id)
    if view is None or view.stale or view.verification_status not in {"verified", "partial"}:
        raise ConflictError("建议已过期或未完成核验，请重新生成")
    text, model = rewrite_reply(context.model_provider, payload.text, payload.instruction)
    issues = rewrite_issues(payload.text, text)
    AuditRecorder(session).record(
        AuditContext.new_turn(actor_type="operator", conversation_id=conversation_id),
        event_type="consumer_suggestion_rewrite", input_text=payload.text,
        detail={"style": payload.style, "instruction": payload.instruction, "model": model,
                "accepted": not issues, "issues": issues},
    )
    if issues:
        session.commit()
        raise ValidationRejected("改写未通过校验，已保留原文：" + issues[0])
    return RewriteView(style=payload.style, text=text, instruction=payload.instruction, model=model)


@router.get("/{conversation_id}/assistant/stream")
async def stream_assistant(
    conversation_id: str, request: Request, style: ReplyStyle | None = None,
    context: RuntimeContext = Depends(get_context),
):
    """按工作流节点推送生成阶段（SSE）。完成事件携带已核验结果；失败推送 error，不伪造成功。"""
    import asyncio
    import json
    import threading

    from app.domain.consumer_service.assistant import ConsumerServiceAssistant
    from app.domain.consumer_service.grounding import record_failure
    from app.errors import YantingError

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    cancelled = threading.Event()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def work() -> None:
        session = context.new_session()
        try:
            view = ConsumerServiceAssistant(session, context.model_provider, runtime=context).build(
                conversation_id, only_style=style, still_current=lambda: not cancelled.is_set(),
                on_step=lambda name, status: emit({"type": "stage", "name": name, "status": status}),
            )
            session.commit()
            emit({"type": "done", "view": view.model_dump(by_alias=True, mode="json")})
        except YantingError as exc:
            session.rollback()
            record_failure(session, conversation_id, exc)
            session.commit()
            emit({"type": "error", "code": getattr(exc, "code", type(exc).__name__), "message": str(exc)})
        except Exception as exc:
            session.rollback()
            emit({"type": "error", "code": "internal_error", "message": str(exc)[:200]})
        finally:
            session.close()
            emit({"type": "_end"})

    threading.Thread(target=work, daemon=True).start()

    async def events():
        try:
            while True:
                event = await queue.get()
                if event["type"] == "_end":
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if await request.is_disconnected():
                    cancelled.set()
                    break
        finally:
            cancelled.set()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
