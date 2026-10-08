"""案件状态机：状态转换的唯一入口。

规则来源：PRD 第 5.2 节与第 4.4 节。

明确不做的事：
- 不设人工处理时限、超时状态或自动升级；
- 后台未操作时案件保持 `pending_review`，不因时钟推进变化；
- 案件 `closed` 不等于设备修好，具体结果由证据和结束说明表达。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import CaseStatus, ConversationStage, RatingStatus, RequestStatus
from app.errors import ValidationRejected

# 允许的案件状态转换。`closed` 是终态，防止「已结束」被静默改回办理中。
CASE_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.OPEN: frozenset(
        {CaseStatus.AWAITING_USER, CaseStatus.PENDING_REVIEW, CaseStatus.CLOSED}
    ),
    CaseStatus.AWAITING_USER: frozenset(
        {CaseStatus.OPEN, CaseStatus.PENDING_REVIEW, CaseStatus.CLOSED}
    ),
    CaseStatus.PENDING_REVIEW: frozenset({CaseStatus.OPEN, CaseStatus.CLOSED}),
    CaseStatus.CLOSED: frozenset(),
}

# 申请状态机。注意没有任何 timeout / auto_* 状态。
REQUEST_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    RequestStatus.DRAFT: frozenset({RequestStatus.PENDING_CONFIRMATION}),
    RequestStatus.PENDING_CONFIRMATION: frozenset(
        {
            RequestStatus.APPROVED,
            RequestStatus.REJECTED,
            RequestStatus.NEEDS_INFORMATION,
        }
    ),
    # 退回补充后可以再次进入待确认；申请内容变更后不能复用旧批准
    RequestStatus.NEEDS_INFORMATION: frozenset(
        {RequestStatus.PENDING_CONFIRMATION, RequestStatus.REJECTED}
    ),
    # 已批准/已拒绝为终态：重复提交或刷新不得再次生效
    RequestStatus.APPROVED: frozenset(),
    RequestStatus.REJECTED: frozenset(),
}

# 会话阶段推进（只允许向前或回到补问）
STAGE_TRANSITIONS: dict[ConversationStage, frozenset[ConversationStage]] = {
    ConversationStage.NEW: frozenset({ConversationStage.INTAKE}),
    ConversationStage.INTAKE: frozenset(
        {
            ConversationStage.DISAMBIGUATION,
            ConversationStage.DIAGNOSIS,
            ConversationStage.ELIGIBILITY,
        }
    ),
    ConversationStage.DISAMBIGUATION: frozenset(
        {ConversationStage.INTAKE, ConversationStage.DIAGNOSIS, ConversationStage.ELIGIBILITY}
    ),
    ConversationStage.DIAGNOSIS: frozenset(
        {
            ConversationStage.ELIGIBILITY,
            ConversationStage.AWAITING_CONFIRMATION,
            ConversationStage.CLOSURE,
        }
    ),
    ConversationStage.ELIGIBILITY: frozenset(
        {
            ConversationStage.AWAITING_CONFIRMATION,
            ConversationStage.CLOSURE,
            ConversationStage.INTAKE,
        }
    ),
    ConversationStage.AWAITING_CONFIRMATION: frozenset(
        {ConversationStage.ELIGIBILITY, ConversationStage.CLOSURE, ConversationStage.INTAKE}
    ),
    ConversationStage.CLOSURE: frozenset({ConversationStage.RATING, ConversationStage.CLOSED}),
    ConversationStage.RATING: frozenset({ConversationStage.CLOSED}),
    ConversationStage.CLOSED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class TransitionResult:
    allowed: bool
    reason: str


def can_transition_case(current: CaseStatus, target: CaseStatus) -> TransitionResult:
    """判断案件状态是否可转换。同一状态视为幂等成功（重复请求不报错）。"""

    if current is target:
        return TransitionResult(True, "状态未变化，按幂等处理")
    allowed = CASE_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        return TransitionResult(
            False,
            f"不允许从 {current.value} 转换到 {target.value}；"
            f"合法目标：{sorted(item.value for item in allowed) or '无（终态）'}",
        )
    return TransitionResult(True, f"{current.value} -> {target.value}")


def assert_case_transition(current: CaseStatus, target: CaseStatus) -> None:
    result = can_transition_case(current, target)
    if not result.allowed:
        raise ValidationRejected(result.reason)


def can_transition_request(current: RequestStatus, target: RequestStatus) -> TransitionResult:
    if current is target:
        return TransitionResult(True, "状态未变化，按幂等处理")
    allowed = REQUEST_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        return TransitionResult(
            False,
            f"不允许从 {current.value} 转换到 {target.value}；"
            f"合法目标：{sorted(item.value for item in allowed) or '无（终态）'}",
        )
    return TransitionResult(True, f"{current.value} -> {target.value}")


def assert_request_transition(current: RequestStatus, target: RequestStatus) -> None:
    result = can_transition_request(current, target)
    if not result.allowed:
        raise ValidationRejected(result.reason)


# 人工确认动作 -> 目标状态。动作名与状态名分开，避免把「批准」这一业务动作
# 与「approved」这一状态混为一谈。
REQUEST_ACTION_TARGET: dict[str, RequestStatus] = {
    "approve": RequestStatus.APPROVED,
    "reject": RequestStatus.REJECTED,
    "request_information": RequestStatus.NEEDS_INFORMATION,
}


def assert_request_action_allowed(current: RequestStatus, action: str) -> TransitionResult:
    """校验「对当前申请状态执行某个人工确认动作」是否合法。

    与状态转换的区别：这里针对的是**动作**。
    对已批准/已拒绝的终态再次执行批准属于新的业务动作，必须拒绝，
    而重复读取同一状态属于幂等重放，不应报错。
    """

    target = REQUEST_ACTION_TARGET.get(action)
    if target is None:
        raise ValidationRejected(f"未知的人工确认动作：{action}")
    if current is RequestStatus.APPROVED:
        raise ValidationRejected("申请已批准，不能再次执行确认动作")
    if current is RequestStatus.REJECTED:
        raise ValidationRejected("申请已拒绝，不能再次执行确认动作")
    if current is not RequestStatus.PENDING_CONFIRMATION:
        raise ValidationRejected(f"申请当前状态为 {current.value}，只有待人工确认的申请可以被处理")
    return TransitionResult(True, f"允许对 {current.value} 执行 {action} -> {target.value}")


def can_transition_stage(current: ConversationStage, target: ConversationStage) -> TransitionResult:
    if current is target:
        return TransitionResult(True, "阶段未变化")
    allowed = STAGE_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        return TransitionResult(
            False,
            f"不允许从阶段 {current.value} 转换到 {target.value}",
        )
    return TransitionResult(True, f"{current.value} -> {target.value}")


def rating_allowed(
    case_status: CaseStatus, request_statuses: list[RequestStatus]
) -> TransitionResult:
    """是否应发起满意度评价。

    PRD 第 5.2 节：评价在**服务结束时**发起；
    「仅进入待后台确认」不等于服务结束，因此不能在 pending_review 时发起。
    """

    if any(status is RequestStatus.PENDING_CONFIRMATION for status in request_statuses):
        return TransitionResult(False, "仍有申请等待后台确认，服务尚未结束")
    if any(status is RequestStatus.DRAFT for status in request_statuses):
        return TransitionResult(False, "存在未提交的申请草稿，服务尚未结束")
    if case_status is not CaseStatus.CLOSED:
        return TransitionResult(False, f"案件状态为 {case_status.value}，尚未结束")
    return TransitionResult(True, "案件已结束，可以发起满意度评价")


def next_rating_status(current: RatingStatus, action: str) -> RatingStatus:
    """评价状态推进。跳过是合法动作，未评价保持空值且不写默认分。"""

    if action == "request":
        if current is RatingStatus.NOT_REQUESTED:
            return RatingStatus.PENDING
        raise ValidationRejected(f"当前评价状态为 {current.value}，不能重复发起")
    if action == "submit":
        if current is not RatingStatus.PENDING:
            raise ValidationRejected(f"当前评价状态为 {current.value}，不能提交评分")
        return RatingStatus.SUBMITTED
    if action == "skip":
        if current is not RatingStatus.PENDING:
            raise ValidationRejected(f"当前评价状态为 {current.value}，不能跳过")
        return RatingStatus.SKIPPED
    raise ValidationRejected(f"未知的评价动作：{action}")
