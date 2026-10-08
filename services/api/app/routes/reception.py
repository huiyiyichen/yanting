from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import Field
from sqlalchemy.orm import Session

from app.deps import get_context, get_session, require_support
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
    session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
):
    from app.domain.consumer_service.assistant import ConsumerServiceAssistant
    from app.domain.consumer_service.grounding import record_failure
    from app.errors import AnkerAgentError

    try:
        return ConsumerServiceAssistant(session, context.model_provider, runtime=context).build(
            conversation_id
        )
    except AnkerAgentError as exc:
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
