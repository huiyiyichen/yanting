"""会话与案件的服务层：路由只做参数与权限，业务逻辑集中在这里。

这样客户侧与客服侧路由共用同一套读写逻辑，避免两处实现分叉导致
「客户看到的和客服看到的不一致」。
"""

from __future__ import annotations

import json
from datetime import UTC
from typing import Any

from sqlalchemy.orm import Session

from app.domain.case_state.models import CaseRow
from app.domain.enums import (
    CaseStatus,
    ComplaintRisk,
    ConversationStage,
    CustomerIntent,
    EmotionLevel,
    RatingStatus,
    RequestStatus,
    SenderRole,
    ServiceMode,
    ViewRole,
)
from app.errors import NotFoundError
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.conversation import (
    CaseView,
    ConversationSummary,
    EvidenceView,
    MessageView,
    QueueItem,
    RequestView,
)


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _parse_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _parse_json_list_of(value: Any) -> list[str]:
    """把 `case_facts_json` 里已经解析出来的列表字段收敛成 `list[str]`。

    与 `_parse_json_list` 的区别：那个接收**原始 JSON 字符串**，这个接收已经
    解析过的值（这里的事实字典是嵌套结构，不能整段当列表解析）。
    """

    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def message_view(row: Any) -> MessageView:
    return MessageView(
        message_id=row.message_id,
        conversation_id=row.conversation_id,
        sender_role=SenderRole(row.sender_role),
        body=row.body,
        message_revision=row.applies_to_message_revision,
        attachments=json.loads(row.attachments_json or "[]"),
        created_at=(
            row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at
        ).isoformat(),
    )


def request_view(row: Any) -> RequestView:
    payload = _parse_json_dict(row.request_payload_json)
    return RequestView(
        request_id=row.request_id,
        request_type=row.request_type,
        request_status=row.request_status,
        request_revision=row.request_revision,
        payload_hash=row.payload_hash,
        summary=str(payload.get("summary") or ""),
        reviewer_role=row.reviewer_role,
        reviewed_at=row.reviewed_at.isoformat() if row.reviewed_at else None,
        review_action=row.review_action,
        review_reason=row.review_reason,
        created_at=row.created_at.isoformat(),
    )


def _evidence_view(item: dict[str, Any]) -> EvidenceView:
    """把检索证据（snake_case 契约）转成 API 视图（camelCase）。

    键名在此**显式映射**，不用 `model_validate` 猜测：
    证据结构由知识契约固定，改名会静默产生空值（已踩过该坑）。
    """

    return EvidenceView(
        retrieval_id=str(item.get("retrieval_id") or ""),
        snapshot_id=str(item.get("snapshot_id") or ""),
        chunk_id=str(item.get("chunk_id") or ""),
        document_id=str(item.get("document_id") or ""),
        document_title=str(item.get("document_title") or ""),
        document_version=str(item.get("document_version") or ""),
        knowledge_base_id=str(item.get("knowledge_base_id") or ""),
        visibility=str(item.get("visibility") or ""),
        heading_path=str(item.get("heading_path") or ""),
        source_locator=str(item.get("source_locator") or ""),
        quoted_excerpt=str(item.get("quoted_excerpt") or ""),
        applicability=item.get("applicability") or {},
        channel_ranks=item.get("channel_ranks") or {},
        rrf_score=float(item.get("rrf_score") or 0.0),
    )


class ConversationService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ConversationRepository(session)

    # ------------------------------------------------------------------ 会话

    def create_conversation(self, *, customer_id: str, title: str | None = None) -> Any:
        return self._repo.create_conversation(customer_id=customer_id, title=title or "新会话")

    def greet_new_conversation(self, conversation: Any) -> Any:
        """给新会话写一条固定的开场白（服务方消息）。

        为什么要落库而不是前端写死：刷新后开场白必须还在，且客户第一次看到的就是
        服务方的自我介绍 + 快捷入口。幂等键固定，重复调用不会插入第二条。
        """

        from app.domain.agent.onboarding import WELCOME_KEY, WELCOME_MESSAGE
        from app.domain.enums import SenderRole

        row, _created = self._repo.append_message(
            conversation,
            sender_role=SenderRole.ASSISTANT,
            body=WELCOME_MESSAGE,
            client_message_key=WELCOME_KEY,
        )
        return row

    def list_summaries(self, *, customer_id: str | None = None) -> list[ConversationSummary]:
        from app.domain.consumer_service.auto_reception import latest_jobs

        jobs = latest_jobs(self._session)
        summaries: list[ConversationSummary] = []
        for row in self._repo.list_conversations(customer_id=customer_id):
            messages = self._repo.list_messages(row.conversation_id)
            case = self._repo.get_case_by_conversation(row.conversation_id)
            last_body = messages[-1].body if messages else ""
            summaries.append(
                ConversationSummary(
                    conversation_id=row.conversation_id,
                    title=row.title,
                    customer_id=row.customer_id,
                    service_mode=ServiceMode(row.service_mode),
                    message_revision=row.message_revision,
                    mode_revision=row.mode_revision,
                    last_message_preview=last_body[:60],
                    message_count=len(messages),
                    case_status=CaseStatus(case.case_status) if case else None,
                    auto_reply_status=jobs[row.conversation_id].status if row.conversation_id in jobs else "idle",
                )
            )
        return summaries

    def get_conversation(self, conversation_id: str) -> Any:
        row = self._repo.get_conversation(conversation_id)
        if row is None:
            raise NotFoundError(f"会话不存在：{conversation_id}")
        return row

    def list_messages(self, conversation_id: str) -> list[MessageView]:
        self.get_conversation(conversation_id)
        return [message_view(row) for row in self._repo.list_messages(conversation_id)]

    def set_service_mode(self, conversation_id: str, mode: ServiceMode) -> Any:
        conversation = self.get_conversation(conversation_id)
        self._repo.set_service_mode(conversation, mode)
        return conversation

    # ------------------------------------------------------------------ 队列

    def support_queue(self) -> list[QueueItem]:
        """客服会话队列。只做展示排序，**不含**任何超时或升级语义。"""

        from app.domain.after_sales.requests import RequestRepository

        requests = RequestRepository(self._session)
        pending_by_case: dict[str, int] = {}
        for row in requests.list_pending():
            pending_by_case[row.case_id] = pending_by_case.get(row.case_id, 0) + 1

        items: list[QueueItem] = []
        for row in self._repo.list_conversations():
            case = self._repo.get_case_by_conversation(row.conversation_id)
            items.append(
                QueueItem(
                    conversation_id=row.conversation_id,
                    case_id=case.case_id if case else None,
                    title=row.title,
                    customer_id=row.customer_id,
                    case_status=CaseStatus(case.case_status) if case else None,
                    service_mode=ServiceMode(row.service_mode),
                    emotion_level=EmotionLevel(case.emotion_level) if case else None,
                    complaint_risk=ComplaintRisk(case.complaint_risk) if case else None,
                    pending_request_count=pending_by_case.get(case.case_id, 0) if case else 0,
                    updated_at=row.updated_at.isoformat(),
                )
            )
        # 待确认优先，其次按更新时间倒序；这不是 SLA，只是展示顺序
        items.sort(
            key=lambda item: (
                0 if item.pending_request_count else 1,
                item.updated_at,
            ),
            reverse=False,
        )
        return items

    # ------------------------------------------------------------------ 案件

    def case_view(self, conversation_id: str, *, include_evidence: bool = True) -> CaseView | None:
        """案件视图。`include_evidence=False` 时不含知识依据（客户侧不使用该结构）。"""

        case: CaseRow | None = self._repo.get_case_by_conversation(conversation_id)
        if case is None:
            return None

        from app.domain.after_sales.requests import RequestRepository

        requests = RequestRepository(self._session)
        evidence: list[EvidenceView] = []
        if include_evidence:
            evidence = self._evidence_for(case)

        return CaseView(
            case_id=case.case_id,
            conversation_id=case.conversation_id,
            case_status=CaseStatus(case.case_status),
            conversation_stage=ConversationStage(case.conversation_stage),
            product_id=case.product_id,
            product_model=case.product_model,
            product_category=case.product_category,
            country_code=case.country_code,
            purchase_channel=case.purchase_channel,
            seller_name_raw=case.seller_name_raw,
            seller_name_standard=case.seller_name_standard,
            customer_intents=[
                CustomerIntent(item) for item in _parse_json_list(case.customer_intents_json)
            ],
            emotion_level=EmotionLevel(case.emotion_level),
            complaint_risk=ComplaintRisk(case.complaint_risk),
            warranty_status=case.warranty_status,
            dealer_authorization_status=case.dealer_authorization_status,
            knowledge_hit_status=case.knowledge_hit_status,
            retrieval_id=case.retrieval_id,
            troubleshooting_result=case.troubleshooting_result,
            rating_status=RatingStatus(case.rating_status),
            user_rating=case.user_rating,
            missing_facts=_parse_json_list(case.missing_facts_json),
            # 图片可见线索存在案件事实里（`case_facts_json.observedFromImage`）：
            # 客服要能核对「模型究竟从图里看到了什么」，未配置多模态时恒为空数组。
            observed_from_image=_parse_json_list_of(
                _parse_json_dict(case.case_facts_json).get("observedFromImage")
            ),
            evidence=evidence,
            requests=[request_view(row) for row in requests.list_for_case(case.case_id)],
            allowed_actions=self._allowed_actions(case),
            forbidden_actions=FORBIDDEN_ACTIONS,
            service_started_at=case.service_started_at.isoformat(),
            updated_at=case.updated_at.isoformat(),
        )

    def _evidence_for(self, case: CaseRow) -> list[EvidenceView]:
        """复读案件当时的检索证据。

        检索证据在发生时以**不可变副本**写入 `case_event`
        （`event_type="knowledge_retrieval"`），因此这里只是读回副本。
        这样即使索引被替换，历史案件仍能按当时的版本复盘（AC-28）。

        注意：这里读的是 `case_event` 而不是 `audit_event`。
        `audit_event` 是追加式审计事件（工具调用、模型调用等），
        两者用途不同，读错表会静默返回空证据。
        """

        if not case.retrieval_id:
            return []
        from sqlalchemy import select

        from app.domain.case_state.models import CaseEventRow

        rows = list(
            self._session.execute(
                select(CaseEventRow)
                .where(CaseEventRow.case_id == case.case_id)
                .where(CaseEventRow.event_type == "knowledge_retrieval")
                .order_by(CaseEventRow.created_at.desc())
            ).scalars()
        )
        for row in rows:
            detail = _parse_json_dict(row.detail_json)
            items = detail.get("evidence") or []
            views = [_evidence_view(item) for item in items if isinstance(item, dict)]
            if views:
                return views
        return []

    @staticmethod
    def _allowed_actions(case: CaseRow) -> list[str]:
        status = CaseStatus(case.case_status)
        if status is CaseStatus.CLOSED:
            return []
        actions = ["knowledge_search"]
        if status is CaseStatus.PENDING_REVIEW:
            actions.append("review_request")
        if case.troubleshooting_result != "resolved":
            actions.append("troubleshooting_plan")
        return actions


# 任何情况下都不允许的动作：本期没有真实业务执行能力
FORBIDDEN_ACTIONS = [
    "execute_refund",
    "execute_replacement",
    "execute_repair_dispatch",
    "execute_parts_shipment",
    "modify_source_order",
    "auto_approve_request",
]


def is_visible_to_customer(*, view_role: ViewRole) -> bool:
    return view_role is ViewRole.CUSTOMER


__all__ = [
    "FORBIDDEN_ACTIONS",
    "ConversationService",
    "RequestStatus",
    "message_view",
    "request_view",
]
