"""客户侧接口。

归属约束（前端规范第 3 节）：客户侧只有会话列表、新建会话、普通消息、
图片与输入框。因此本模块**不返回** AI 判断、内部依据、审批控件或工具轨迹
（AC-24：客服功能不泄露到客户页）。
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_context, get_session, require_customer
from app.domain.enums import ViewRole
from app.repositories.attachment_service import validate_and_store_image
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.conversation_service import ConversationService, message_view
from app.routes.commit import CommitBeforeResponseRoute
from app.runtime import RuntimeContext
from app.schemas.base import ApiModel
from app.schemas.conversation import (
    AttachmentView,
    ConversationSummary,
    CreateConversationRequest,
    MessageView,
    RatingRequest,
    RatingView,
    SendMessageRequest,
    SendMessageResponse,
    ServiceModeView,
    VisionAvailabilityView,
)

router = APIRouter(
    prefix="/api/customer",
    tags=["customer"],
    # 事务必须在响应发出**之前**提交，否则「写 200 已返回、紧接着的读看不到」
    # 会真实发生（缺陷第 49 项，原因与验证见 app/routes/commit.py）。
    route_class=CommitBeforeResponseRoute,
)


class QuickReplyView(ApiModel):
    """一个快捷入口：按钮文字 + 点击后真正发出的那句话。"""

    label: str
    prompt: str


class OnboardingView(ApiModel):
    """新会话开场白的固定文案与快捷入口（唯一来源在后端）。"""

    greeting: str
    quick_replies: list[QuickReplyView]


def _attachment_data_url(context: RuntimeContext, row: Any) -> str | None:
    """把已存附件读回并编码成 data URL，供视觉模型使用。

    只读取 `data/runtime/attachments/` 下的系统生成路径；文件缺失时返回 None
    （调用方会跳过），绝不因为一张图读不到就让整条消息失败——客户的消息本身
    仍然有效，这一点比图片更重要。
    """

    from pathlib import Path

    path = Path(row.stored_path)
    if not path.is_absolute():
        path = context.settings.runtime_path / path
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{row.mime_type};base64,{encoded}"


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    customer_id: str = "CUST-DEMO-01",
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_customer),
) -> list[ConversationSummary]:
    return ConversationService(session).list_summaries(customer_id=customer_id)


@router.post("/conversations", response_model=ConversationSummary)
async def create_conversation(
    payload: CreateConversationRequest,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_customer),
) -> ConversationSummary:
    service = ConversationService(session)
    row = service.create_conversation(customer_id=payload.customer_id, title=payload.title)
    # 新会话先写一条固定开场白（含快捷入口提示），客户进来不会看到空白页
    service.greet_new_conversation(row)
    # 显式提交：第 26 项实测「刚创建的会话立刻被读会 404」（对照实验 10/25 = 40%
    # 失败），当时就在创建类接口上补了这一步。现在全局时序已由
    # `CommitBeforeResponseRoute` 保证（见 app/routes/commit.py，第 49 项），
    # 这里保留显式提交：创建接口的「先落库再返回」是最关键的一条，写成本地可见
    # 比依赖全局机制更不容易被后人改错；重复提交本身是空操作。
    session.commit()
    return ConversationSummary(
        conversation_id=row.conversation_id,
        title=row.title,
        customer_id=row.customer_id,
        service_mode=row.service_mode,  # type: ignore[arg-type]
        message_revision=row.message_revision,
        mode_revision=row.mode_revision,
    )


@router.get("/onboarding", response_model=OnboardingView)
async def onboarding(_role: ViewRole = Depends(require_customer)) -> OnboardingView:
    """新会话开场白的固定文案与快捷入口（唯一来源在后端）。

    前端只在「该会话还没有客户消息」时展示快捷选项；用户不点、直接打字也走
    同一个发送接口与同一套编排，不做"点按钮才有的特殊分支"。
    """

    from app.domain.agent.onboarding import WELCOME_MESSAGE, quick_replies

    return OnboardingView(
        greeting=WELCOME_MESSAGE,
        quick_replies=[
            QuickReplyView(label=item.label, prompt=item.prompt) for item in quick_replies()
        ],
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageView])
async def list_messages(
    conversation_id: str,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_customer),
) -> list[MessageView]:
    return ConversationService(session).list_messages(conversation_id)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SendMessageResponse,
)
async def send_message(
    conversation_id: str,
    payload: SendMessageRequest,
    request: Request,
    session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_customer),
) -> SendMessageResponse:
    """客户发送消息并触发 Agent 处理。

    幂等：同一 `clientMessageKey` 重复提交不追加第二条消息，也不重复调用模型。
    客户侧响应**不包含**内部判断明细，只返回消息本身与自动回复。
    """

    repo = ConversationRepository(session)
    conversation = repo.get_conversation(conversation_id)
    if conversation is None:
        from app.errors import NotFoundError

        raise NotFoundError(f"会话不存在：{conversation_id}")

    # 附件：前端先上传、再随消息发送。这里把附件还原成 data URL 交给编排器，
    # 视觉模型才能真的看到图片；同时校验附件属于本会话，避免跨会话引用。
    attachments = repo.list_attachments(payload.attachment_ids)
    if len(attachments) != len(set(payload.attachment_ids)):
        from app.errors import ValidationRejected

        raise ValidationRejected("存在无效的附件编号")
    for item in attachments:
        if item.conversation_id != conversation_id:
            from app.errors import ValidationRejected

            raise ValidationRejected("附件不属于当前会话")

    from app.audit.recorder import AuditContext, AuditRecorder
    from app.domain.enums import SenderRole
    from app.errors import ValidationRejected

    if not payload.body.strip() and not attachments:
        raise ValidationRejected("消息不能为空")
    customer_message, created = repo.append_message(
        conversation,
        sender_role=SenderRole.CUSTOMER,
        body=payload.body,
        client_message_key=payload.client_message_key,
        attachments=[
            {
                "attachmentId": item.attachment_id,
                "mimeType": item.mime_type,
                "byteSize": item.byte_size,
                "width": item.width,
                "height": item.height,
                "url": f"/api/customer/attachments/{item.attachment_id}/content",
            }
            for item in attachments
        ],
    )

    # 建立附件与消息的关联：不关联的话图片永远只是孤儿附件，
    # 消息里看不到、后续也追溯不到（实测踩到过）。
    if attachments and customer_message.message_id:
        repo.link_attachments(
            [item.attachment_id for item in attachments], customer_message.message_id
        )

    if created:
        AuditRecorder(session).record(
            AuditContext.new_turn(actor_type="customer", conversation_id=conversation_id),
            event_type="customer_message",
            input_text=payload.body,
            detail={"messageId": customer_message.message_id},
        )
        # All reception modes share the rule engine; never expose internal observations to customers.
        from app.domain.consumer_service.risk_rules import evaluate_risks

        evaluate_risks(session)
        from app.domain.consumer_service.auto_reception import enqueue_reply

        enqueue_reply(session, conversation, customer_message)
    del request
    return SendMessageResponse(
        message=message_view(customer_message),
        created=created,
        reply=None,
        # 客户侧不返回 decision 明细；保留字段为 None，避免误传内部信息
        decision=None,
    )


@router.post("/conversations/{conversation_id}/handoff", response_model=ServiceModeView)
def request_handoff(
    conversation_id: str, session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_customer),
) -> ServiceModeView:
    from app.domain.consumer_service.auto_reception import change_mode
    from app.domain.enums import ServiceMode

    ConversationService(session).get_conversation(conversation_id)
    return change_mode(session, conversation_id, ServiceMode.OPERATOR_ASSISTED,
                       actor="customer", reason="customer_requested")


@router.post(
    "/conversations/{conversation_id}/rating",
    response_model=RatingView,
)
async def submit_rating(
    conversation_id: str,
    payload: RatingRequest,
    session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_customer),
) -> RatingView:
    """服务结束时的 1—5 分评价，可跳过。未评价保持空值，不填默认分。"""

    service = ConversationService(session)
    case = service.case_view(conversation_id, include_evidence=False)
    if case is None:
        from app.errors import NotFoundError

        raise NotFoundError("该会话尚未创建案件，无法评价")

    gateway = context.build_gateway(session)
    result = gateway.invoke(
        "record_rating",
        {"caseId": case.case_id, "action": payload.action, "rating": payload.rating},
        as_agent=False,
    )
    if not result.ok:
        from app.errors import ValidationRejected

        raise ValidationRejected(result.message)

    return RatingView(
        case_id=case.case_id,
        rating_status=result.data["ratingStatus"],
        user_rating=result.data.get("userRating"),
    )


@router.get("/conversations/{conversation_id}/rating", response_model=RatingView | None)
async def get_rating(
    conversation_id: str,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_customer),
) -> RatingView | None:
    service = ConversationService(session)
    case = service.case_view(conversation_id, include_evidence=False)
    if case is None:
        return None
    return RatingView(
        case_id=case.case_id,
        rating_status=case.rating_status,
        user_rating=case.user_rating,
    )


@router.get("/vision", response_model=VisionAvailabilityView)
async def vision_availability(
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_customer),
) -> VisionAvailabilityView:
    """图片能力的真实状态。前端据此决定是否展示上传入口。"""

    configured = context.model_provider.supports_vision
    return VisionAvailabilityView(
        vision_configured=configured,
        max_bytes=context.settings.image_max_bytes,
        allowed_mime_types=context.settings.allowed_image_mimes,
        note=(
            "已配置多模态模型，可从图片提取可见线索"
            if configured
            else "未配置多模态模型：可以上传图片，但无法从图片提取线索并会如实报错，不会猜测"
        ),
    )


@router.get("/attachments/{attachment_id}/content")
async def attachment_content(
    attachment_id: str,
    session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_customer),
) -> Response:
    """读取附件原图。

    存在的理由：消息里只保存附件**元数据**（避免把 base64 塞进消息、把会话响应
    撑大几十倍），前端靠这个地址渲染缩略图。路径只来自系统生成值，不拼接用户输入。
    """

    from pathlib import Path

    from app.errors import NotFoundError

    rows = ConversationRepository(session).list_attachments([attachment_id])
    if not rows:
        raise NotFoundError("附件不存在")
    row = rows[0]
    path = Path(row.stored_path)
    if not path.is_absolute():
        path = context.settings.runtime_path / path
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise NotFoundError("附件文件已不存在") from exc
    return Response(
        content=raw,
        media_type=row.mime_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post(
    "/conversations/{conversation_id}/attachments",
    response_model=AttachmentView,
)
async def upload_attachment(
    conversation_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    context: RuntimeContext = Depends(get_context),
    _role: ViewRole = Depends(require_customer),
) -> AttachmentView:
    """上传图片。

    校验：仅 JPEG/PNG/WebP、每张不超过配置上限；**实际类型与可解码性由后端确认**，
    不接受扩展名或前端声明作为依据。文件只落到 `data/runtime/attachments/`。
    """

    service = ConversationService(session)
    service.get_conversation(conversation_id)

    data = await file.read()
    stored = validate_and_store_image(
        data=data,
        declared_mime=file.content_type,
        settings=context.settings,
        conversation_id=conversation_id,
    )

    repo = ConversationRepository(session)
    row = repo.add_attachment(
        conversation_id=conversation_id,
        message_id=None,
        mime_type=stored.mime_type,
        byte_size=stored.byte_size,
        stored_path=stored.stored_path,
        sha256=stored.sha256,
        width=stored.width,
        height=stored.height,
    )
    # 同 create_conversation：attachment_id 返回给客户端前必须先落库。
    # 全局时序由 `CommitBeforeResponseRoute` 保证，这里保留显式提交的理由同上。
    session.commit()
    return AttachmentView(
        attachment_id=row.attachment_id,
        conversation_id=row.conversation_id,
        message_id=row.message_id,
        mime_type=row.mime_type,
        byte_size=row.byte_size,
        width=row.width,
        height=row.height,
        sha256=row.sha256,
        created_at=row.created_at.isoformat(),
    )


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    session: Session = Depends(get_session),
    _role: ViewRole = Depends(require_customer),
) -> dict[str, Any]:
    """删除会话及其全部依赖数据（消息、附件、案件、申请、候选）。

    为什么允许删除：本机 Demo 会累积大量演示会话（实测数百条），没有删除入口
    就只能手工清库。**审计不删**：`audit_event` 是追加式追溯记录，删除动作本身
    也会写一条 `conversation_deleted`，否则「会话不见了」在追溯链上是空洞。
    """

    from app.audit.recorder import AuditContext, AuditRecorder

    repo = ConversationRepository(session)
    counts = repo.delete_conversation(conversation_id)
    AuditRecorder(session).record(
        AuditContext.new_turn(actor_type="customer", conversation_id=conversation_id),
        event_type="conversation_deleted",
        detail={"deleted": counts, "note": "审计保留，仅删除业务数据"},
    )
    session.flush()
    return {"conversationId": conversation_id, "deleted": counts}
