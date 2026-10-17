"""服务结束后的满意度评价（原 after_sales 工具 record_rating 迁来，P2-1）。

规则不变（PRD 第 5.2 节）：服务未结束或仍有待确认申请时不允许发起；提交必须带 1–5 分；跳过时评分为空。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationRejected


def record_rating(session: Session, case_id: str, action: str, rating: int | None = None) -> dict:
    from app.domain.case_state.state_machine import next_rating_status, rating_allowed
    from app.domain.enums import CaseStatus, RatingStatus, RequestStatus
    from app.repositories.conversation_repository import ConversationRepository

    repo = ConversationRepository(session)
    case = repo.get_case(case_id)
    if case is None:
        raise NotFoundError(f"案件不存在：{case_id}")
    if action == "request":
        gate = rating_allowed(CaseStatus(case.case_status),
                              [RequestStatus(item.request_status) for item in repo.list_open_requests(case_id)])
        if not gate.allowed:
            raise ValidationRejected(gate.reason)
    try:
        target = next_rating_status(RatingStatus(case.rating_status), action)
    except Exception as exc:  # 状态机拒绝的动作
        raise ValidationRejected(str(exc)) from exc
    if action == "submit" and rating is None:
        raise ValidationRejected("提交评价时必须提供 1—5 的评分")
    repo.set_rating(case, status=target, rating=rating if action == "submit" else None)
    return {"caseId": case_id, "ratingStatus": target.value, "userRating": case.user_rating}
