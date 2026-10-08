"""案件与申请状态机测试。

覆盖 PRD 第 4.4 节与第 5.2 节的硬规则：
- 不存在人工超时/自动批准/自动升级状态；
- 已批准/已拒绝是终态，重复批准不再次生效；
- 「仅进入待后台确认」不等于服务结束，不得提前发起评价；
- 评分只能是 1—5 或空值。
"""

from __future__ import annotations

import pytest

from app.domain.case_state import state_machine as sm
from app.domain.enums import CaseStatus, ConversationStage, RatingStatus, RequestStatus
from app.errors import ValidationRejected


class TestCaseStatusMachine:
    def test_open_can_go_to_awaiting_user(self) -> None:
        assert sm.can_transition_case(CaseStatus.OPEN, CaseStatus.AWAITING_USER).allowed

    def test_open_can_go_to_pending_review(self) -> None:
        assert sm.can_transition_case(CaseStatus.OPEN, CaseStatus.PENDING_REVIEW).allowed

    def test_pending_review_can_return_to_open(self) -> None:
        assert sm.can_transition_case(CaseStatus.PENDING_REVIEW, CaseStatus.OPEN).allowed

    def test_closed_is_terminal(self) -> None:
        for target in CaseStatus:
            result = sm.can_transition_case(CaseStatus.CLOSED, target)
            if target is CaseStatus.CLOSED:
                assert result.allowed, "同一状态应按幂等处理"
            else:
                assert not result.allowed, f"closed 不应能转到 {target.value}"

    def test_same_status_is_idempotent_success(self) -> None:
        result = sm.can_transition_case(CaseStatus.OPEN, CaseStatus.OPEN)
        assert result.allowed
        assert "幂等" in result.reason

    def test_no_manual_timeout_state_exists(self) -> None:
        """案件状态里不得出现任何人工超时/升级状态。"""

        values = {item.value for item in CaseStatus}
        assert values == {"open", "awaiting_user", "pending_review", "closed"}
        for forbidden in ("timeout", "expired", "escalated", "auto_closed", "sla_breach"):
            assert forbidden not in values


class TestRequestStatusMachine:
    def test_draft_to_pending_confirmation(self) -> None:
        assert sm.can_transition_request(
            RequestStatus.DRAFT, RequestStatus.PENDING_CONFIRMATION
        ).allowed

    def test_pending_requires_human_decision(self) -> None:
        """待确认只能由人工操作推进，不存在自动路径。"""

        allowed = sm.REQUEST_TRANSITIONS[RequestStatus.PENDING_CONFIRMATION]
        assert allowed == {
            RequestStatus.APPROVED,
            RequestStatus.REJECTED,
            RequestStatus.NEEDS_INFORMATION,
        }

    def test_approved_and_rejected_are_terminal(self) -> None:
        assert sm.REQUEST_TRANSITIONS[RequestStatus.APPROVED] == frozenset()
        assert sm.REQUEST_TRANSITIONS[RequestStatus.REJECTED] == frozenset()

    def test_duplicate_approval_action_is_rejected(self) -> None:
        """对已批准申请再次执行「批准」动作必须被拒绝。

        注意与「幂等重放」的区别：
        - 状态机把**同一状态**视为幂等成功（重复读取/重放请求不报错）；
        - 但「对终态再次执行批准动作」是新的业务动作，必须拒绝。
          仓库层还会按 `approved_revision` 判重，二者共同保证 AC-29 的
          「重复批准 0 次」。
        """

        with pytest.raises(ValidationRejected):
            sm.assert_request_action_allowed(RequestStatus.APPROVED, "approve")
        with pytest.raises(ValidationRejected):
            sm.assert_request_action_allowed(RequestStatus.REJECTED, "reject")

    def test_request_action_allowed_only_from_pending(self) -> None:
        for action in ("approve", "reject", "request_information"):
            assert sm.assert_request_action_allowed(
                RequestStatus.PENDING_CONFIRMATION, action
            ).allowed
            with pytest.raises(ValidationRejected):
                sm.assert_request_action_allowed(RequestStatus.DRAFT, action)

    def test_needs_information_can_be_resubmitted(self) -> None:
        assert sm.can_transition_request(
            RequestStatus.NEEDS_INFORMATION, RequestStatus.PENDING_CONFIRMATION
        ).allowed

    def test_no_timeout_or_auto_states(self) -> None:
        values = {item.value for item in RequestStatus}
        assert values == {
            "draft",
            "pending_confirmation",
            "approved",
            "rejected",
            "needs_information",
        }
        for forbidden in ("timeout", "auto_approved", "auto_rejected", "escalated"):
            assert forbidden not in values


class TestStageMachine:
    def test_forward_path_is_allowed(self) -> None:
        assert sm.can_transition_stage(
            ConversationStage.INTAKE, ConversationStage.DISAMBIGUATION
        ).allowed
        assert sm.can_transition_stage(
            ConversationStage.DIAGNOSIS, ConversationStage.ELIGIBILITY
        ).allowed

    def test_closed_stage_is_terminal(self) -> None:
        assert not sm.can_transition_stage(
            ConversationStage.CLOSED, ConversationStage.INTAKE
        ).allowed


class TestRatingGating:
    def test_pending_review_does_not_trigger_rating(self) -> None:
        """核心规则：单纯待后台确认不等于服务结束。"""

        result = sm.rating_allowed(CaseStatus.PENDING_REVIEW, [RequestStatus.PENDING_CONFIRMATION])
        assert not result.allowed
        assert "尚未结束" in result.reason

    def test_draft_blocks_rating(self) -> None:
        result = sm.rating_allowed(CaseStatus.OPEN, [RequestStatus.DRAFT])
        assert not result.allowed

    def test_open_case_blocks_rating(self) -> None:
        result = sm.rating_allowed(CaseStatus.OPEN, [])
        assert not result.allowed

    def test_closed_case_allows_rating(self) -> None:
        result = sm.rating_allowed(CaseStatus.CLOSED, [])
        assert result.allowed

    def test_closed_with_approved_request_allows_rating(self) -> None:
        result = sm.rating_allowed(CaseStatus.CLOSED, [RequestStatus.APPROVED])
        assert result.allowed


class TestRatingStatus:
    def test_request_then_submit(self) -> None:
        pending = sm.next_rating_status(RatingStatus.NOT_REQUESTED, "request")
        assert pending is RatingStatus.PENDING
        assert sm.next_rating_status(pending, "submit") is RatingStatus.SUBMITTED

    def test_request_then_skip(self) -> None:
        pending = sm.next_rating_status(RatingStatus.NOT_REQUESTED, "request")
        assert sm.next_rating_status(pending, "skip") is RatingStatus.SKIPPED

    def test_cannot_submit_without_requesting(self) -> None:
        with pytest.raises(ValidationRejected):
            sm.next_rating_status(RatingStatus.NOT_REQUESTED, "submit")

    def test_cannot_request_twice(self) -> None:
        with pytest.raises(ValidationRejected):
            sm.next_rating_status(RatingStatus.SUBMITTED, "request")

    def test_unknown_action_rejected(self) -> None:
        with pytest.raises(ValidationRejected):
            sm.next_rating_status(RatingStatus.PENDING, "approve")
