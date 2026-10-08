"""售后申请草稿与人工确认测试。

覆盖 PRD AC-11（后台确认状态完整性）、AC-29（重复批准 0 次）与第 4.4 节规则：
- 批准绑定 request_id + request_revision + payload_hash；
- 内容变更使旧确认失效；
- 拒绝/退回必须给原因；
- 未操作时保持待确认，**不设超时、不自动批准/拒绝**。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.domain.after_sales.requests import RequestRepository
from app.domain.case_state.models import Base
from app.domain.enums import RequestStatus, RequestType
from app.errors import ConflictError
from app.repositories.conversation_repository import ConversationRepository


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'req.sqlite3'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = factory()
    try:
        yield db
        db.commit()
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def prepared_case(session: Session) -> str:
    """准备一个已确认型号与国家/地区的案件（生成草稿的前置条件）。"""

    repo = ConversationRepository(session)
    conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
    case, _ = repo.create_case_for_conversation(conversation)
    repo.update_case_facts(
        case,
        product_model="A1 Pro",
        product_id="PRD-A1P-STICK",
        country_code="CN",
        purchase_channel="official_website",
        warranty_status="in_warranty",
    )
    return case.case_id


class TestDraftCreation:
    def test_draft_requires_confirmed_facts(self, session: Session) -> None:
        """缺少型号或国家/地区时不得生成高质量办理草稿。"""

        repo = ConversationRepository(session)
        conversation = repo.create_conversation(customer_id="CUST-DEMO-02")
        case, _ = repo.create_case_for_conversation(conversation)
        requests = RequestRepository(session)

        outcome = requests.create_draft(
            case_id=case.case_id,
            request_type=RequestType.REFUND,
            summary="用户要求退款",
            payload={},
        )
        assert outcome.error_code == "conflict"
        assert "必须先确认" in outcome.message
        assert outcome.request_id is None

    def test_draft_created_and_pending(self, session: Session, prepared_case: str) -> None:
        requests = RequestRepository(session)
        outcome = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REFUND,
            summary="吸力不足要求退款",
            payload={"reason": "weak_suction"},
        )
        assert outcome.created is True
        assert outcome.request_status == RequestStatus.PENDING_CONFIRMATION.value
        assert outcome.request_revision == 1

    def test_idempotent_creation_returns_same_request(
        self, session: Session, prepared_case: str
    ) -> None:
        requests = RequestRepository(session)
        first = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REFUND,
            summary="要求退款",
            payload={"reason": "x"},
            idempotency_key="draft-key-1",
        )
        second = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REFUND,
            summary="要求退款",
            payload={"reason": "x"},
            idempotency_key="draft-key-1",
        )
        assert first.request_id == second.request_id
        assert second.created is False
        assert len(requests.list_for_case(prepared_case)) == 1

    def test_same_case_same_type_does_not_duplicate(
        self, session: Session, prepared_case: str
    ) -> None:
        """同案件同类型的未结申请不重复创建，即使幂等键不同。"""

        requests = RequestRepository(session)
        first = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REFUND,
            summary="要求退款 A",
            payload={"reason": "a"},
            idempotency_key="k-a",
        )
        second = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REFUND,
            summary="要求退款 B",
            payload={"reason": "b"},
            idempotency_key="k-b",
        )
        assert first.request_id == second.request_id
        assert second.created is False
        assert len(requests.list_for_case(prepared_case)) == 1


class TestReview:
    def test_approve(self, session: Session, prepared_case: str) -> None:
        requests = RequestRepository(session)
        draft = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REFUND,
            summary="退款",
            payload={},
        )
        assert draft.request_id
        result = requests.review(draft.request_id, action="approve", reviewer_role="support")
        assert result.request_status == RequestStatus.APPROVED.value
        assert "不代表真实业务已完成" in result.message
        row = requests.get(draft.request_id)
        assert row.approved_revision == 1
        assert row.reviewed_at is not None

    def test_reject_requires_reason(self, session: Session, prepared_case: str) -> None:
        requests = RequestRepository(session)
        draft = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REPLACEMENT,
            summary="换货",
            payload={},
        )
        assert draft.request_id
        with pytest.raises(ConflictError, match="必须给出固定原因"):
            requests.review(draft.request_id, action="reject", reviewer_role="support")

    def test_request_information_requires_reason(
        self, session: Session, prepared_case: str
    ) -> None:
        requests = RequestRepository(session)
        draft = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REPAIR,
            summary="维修",
            payload={},
        )
        assert draft.request_id
        with pytest.raises(ConflictError):
            requests.review(draft.request_id, action="request_information", reviewer_role="support")

    def test_needs_information_then_resubmit(self, session: Session, prepared_case: str) -> None:
        requests = RequestRepository(session)
        draft = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REPAIR,
            summary="维修",
            payload={},
        )
        assert draft.request_id
        requests.review(
            draft.request_id,
            action="request_information",
            reviewer_role="support",
            reason="missing_purchase_proof",
        )
        row = requests.get(draft.request_id)
        assert row.request_status == RequestStatus.NEEDS_INFORMATION.value

        requests.revise(draft.request_id, payload={"proof": "uploaded"})
        row = requests.get(draft.request_id)
        assert row.request_revision == 2
        assert row.request_status == RequestStatus.PENDING_CONFIRMATION.value

    def test_duplicate_approval_is_rejected(self, session: Session, prepared_case: str) -> None:
        """AC-29：重复批准不重复记账。"""

        requests = RequestRepository(session)
        draft = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REFUND,
            summary="退款",
            payload={},
        )
        assert draft.request_id
        requests.review(draft.request_id, action="approve", reviewer_role="support")
        with pytest.raises(Exception, match="已批准"):
            requests.review(draft.request_id, action="approve", reviewer_role="support")

    def test_stale_revision_is_rejected(self, session: Session, prepared_case: str) -> None:
        """旧版本的批准必须失效（批准绑定内容版本）。"""

        requests = RequestRepository(session)
        draft = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REFUND,
            summary="退款",
            payload={},
        )
        assert draft.request_id
        stale_hash = requests.get(draft.request_id).payload_hash
        requests.revise(draft.request_id, payload={"reason": "changed"})

        with pytest.raises(ConflictError, match="版本已变化"):
            requests.review(
                draft.request_id,
                action="approve",
                reviewer_role="support",
                expected_revision=1,
            )
        with pytest.raises(ConflictError, match="内容已变化"):
            requests.review(
                draft.request_id,
                action="approve",
                reviewer_role="support",
                expected_payload_hash=stale_hash,
            )

    def test_revision_bumps_and_clears_approval(self, session: Session, prepared_case: str) -> None:
        requests = RequestRepository(session)
        draft = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REPLACEMENT,
            summary="换货",
            payload={},
        )
        assert draft.request_id
        requests.review(
            draft.request_id,
            action="request_information",
            reviewer_role="support",
            reason="need_proof",
        )
        requests.revise(draft.request_id, payload={"a": 1})
        row = requests.get(draft.request_id)
        assert row.approved_revision is None
        assert row.request_revision == 2


class TestNoManualTimeout:
    def test_pending_list_has_no_timeout_semantics(
        self, session: Session, prepared_case: str
    ) -> None:
        """未操作时一直待确认：再次查询仍在队列中，状态不变。"""

        requests = RequestRepository(session)
        draft = requests.create_draft(
            case_id=prepared_case,
            request_type=RequestType.REFUND,
            summary="退款",
            payload={},
        )
        first = requests.list_pending()
        second = requests.list_pending()
        assert [row.request_id for row in first] == [row.request_id for row in second]
        assert draft.request_id in {row.request_id for row in second}
        row = requests.get(draft.request_id)  # type: ignore[arg-type]
        assert row.request_status == RequestStatus.PENDING_CONFIRMATION.value
        assert row.reviewed_at is None

    def test_request_status_enum_has_no_timeout_values(self) -> None:
        assert {item.value for item in RequestStatus} == {
            "draft",
            "pending_confirmation",
            "approved",
            "rejected",
            "needs_information",
        }
