"""会话、消息与案件仓储的集成测试（真实 SQLite）。

覆盖 AC-23（多会话隔离）、AC-25（采用不等于发送）、AC-29（竞态/幂等）
以及 PRD 第 13.2 节的并发版本要求。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.domain.case_state.models import Base
from app.domain.enums import (
    CaseStatus,
    ConversationStage,
    EmotionLevel,
    RatingStatus,
    SenderRole,
    ServiceMode,
    TroubleshootingResult,
)
from app.errors import ValidationRejected
from app.repositories.conversation_repository import ConversationRepository


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test.sqlite3'}", future=True)
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
def repo(session: Session) -> ConversationRepository:
    return ConversationRepository(session)


class TestMessageIdempotency:
    def test_duplicate_client_key_does_not_append(self, repo: ConversationRepository) -> None:
        """AC-29：重复提交同一幂等键只落一条消息，且不递增 message_revision。"""

        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        first, created_first = repo.append_message(
            conversation,
            sender_role=SenderRole.CUSTOMER,
            body="我的吸尘器不吸了",
            client_message_key="key-1",
        )
        revision_after_first = conversation.message_revision
        second, created_second = repo.append_message(
            conversation,
            sender_role=SenderRole.CUSTOMER,
            body="我的吸尘器不吸了",
            client_message_key="key-1",
        )

        assert created_first is True
        assert created_second is False
        assert first.message_id == second.message_id
        assert repo.count_messages(conversation.conversation_id) == 1
        assert conversation.message_revision == revision_after_first

    def test_committed_duplicate_key_is_returned_not_reinserted(
        self, repo: ConversationRepository, session: Session, tmp_path: Path
    ) -> None:
        """AC-29 并发幂等：并发提交后，重复键必须返回**已提交的那一行**。

        对应真实缺陷：同一 `client_message_key` 的两个请求都在对方提交前读不到
        对方，于是都执行 INSERT，后到者撞 `UNIQUE constraint failed:
        message.conversation_id, message.client_message_key` 并冒泡成 HTTP 500
        （并发重放同一幂等键时稳定复现，修复后 8/8 轮全部 200）。

        这里固定「另一个请求已经提交」这一状态：本仓库必须返回那一行且
        `created=False`，不得再插一条，也不得丢出约束错误。
        """

        from sqlalchemy import create_engine, text

        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        session.commit()

        other_engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test.sqlite3'}", future=True)
        try:
            with other_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO message (message_id, conversation_id, sender_role, body,"
                        " applies_to_message_revision, client_message_key, attachments_json,"
                        " created_at) VALUES (:mid, :cid, 'customer', :body, 1, :key, '[]',"
                        " datetime('now'))"
                    ),
                    {
                        "mid": "msg-from-other-request",
                        "cid": conversation.conversation_id,
                        "body": "并发幂等",
                        "key": "race-key",
                    },
                )
        finally:
            other_engine.dispose()

        stored, created = repo.append_message(
            conversation,
            sender_role=SenderRole.CUSTOMER,
            body="并发幂等",
            client_message_key="race-key",
        )

        assert created is False
        assert stored.message_id == "msg-from-other-request"
        assert repo.count_messages(conversation.conversation_id) == 1

    def test_distinct_keys_append_distinct_messages(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        repo.append_message(
            conversation,
            sender_role=SenderRole.CUSTOMER,
            body="第一条",
            client_message_key="k1",
        )
        repo.append_message(
            conversation,
            sender_role=SenderRole.CUSTOMER,
            body="第二条",
            client_message_key="k2",
        )
        assert repo.count_messages(conversation.conversation_id) == 2
        assert conversation.message_revision == 2

    def test_first_customer_message_becomes_title(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        repo.append_message(
            conversation,
            sender_role=SenderRole.CUSTOMER,
            body="我的 S1 Pro 吸力不行了还漏水，能退款吗？",
            client_message_key="k1",
        )
        assert conversation.title == "我的 S1 Pro 吸力不行了还"

    def test_service_message_does_not_set_title(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        repo.append_message(
            conversation,
            sender_role=SenderRole.ASSISTANT,
            body="您好，请问遇到什么问题？",
            client_message_key="k1",
        )
        assert conversation.title == "新会话"

    def test_message_order_is_stable(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        for index in range(5):
            repo.append_message(
                conversation,
                sender_role=SenderRole.CUSTOMER,
                body=f"第 {index} 条",
                client_message_key=f"k{index}",
            )
        bodies = [item.body for item in repo.list_messages(conversation.conversation_id)]
        assert bodies == [f"第 {index} 条" for index in range(5)]


class TestConversationIsolation:
    def test_two_conversations_do_not_share_messages(self, repo: ConversationRepository) -> None:
        """AC-23：多会话消息不串线。"""

        first = repo.create_conversation(customer_id="CUST-DEMO-01")
        second = repo.create_conversation(customer_id="CUST-DEMO-01")
        repo.append_message(
            first,
            sender_role=SenderRole.CUSTOMER,
            body="会话一的消息",
            client_message_key="a",
        )
        repo.append_message(
            second,
            sender_role=SenderRole.CUSTOMER,
            body="会话二的消息",
            client_message_key="b",
        )

        assert [m.body for m in repo.list_messages(first.conversation_id)] == ["会话一的消息"]
        assert [m.body for m in repo.list_messages(second.conversation_id)] == ["会话二的消息"]
        assert first.conversation_id != second.conversation_id

    def test_same_client_key_in_different_conversations_is_allowed(
        self, repo: ConversationRepository
    ) -> None:
        """幂等键只在会话内唯一：不同会话使用相同键是合法的。"""

        first = repo.create_conversation(customer_id="CUST-DEMO-01")
        second = repo.create_conversation(customer_id="CUST-DEMO-01")
        _, created_a = repo.append_message(
            first, sender_role=SenderRole.CUSTOMER, body="A", client_message_key="same"
        )
        _, created_b = repo.append_message(
            second, sender_role=SenderRole.CUSTOMER, body="B", client_message_key="same"
        )
        assert created_a and created_b
        assert repo.count_messages(first.conversation_id) == 1
        assert repo.count_messages(second.conversation_id) == 1


class TestCaseLifecycle:
    def test_case_created_once_per_conversation(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, created = repo.create_case_for_conversation(conversation)
        again, created_again = repo.create_case_for_conversation(conversation)
        assert created is True
        assert created_again is False
        assert case.case_id == again.case_id

    def test_case_creation_records_event(self, repo: ConversationRepository) -> None:
        from sqlalchemy import select

        from app.domain.case_state.models import CaseEventRow

        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        events = list(
            repo._session.execute(
                select(CaseEventRow).where(CaseEventRow.case_id == case.case_id)
            ).scalars()
        )
        assert len(events) == 1
        assert events[0].event_type == "case_created"

    def test_status_transition_records_event(self, repo: ConversationRepository) -> None:
        from sqlalchemy import select

        from app.domain.case_state.models import CaseEventRow

        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        changed = repo.set_case_status(case, CaseStatus.PENDING_REVIEW)
        assert changed is True
        assert case.case_status == CaseStatus.PENDING_REVIEW.value

        events = list(
            repo._session.execute(
                select(CaseEventRow).where(CaseEventRow.event_type == "case_status_changed")
            ).scalars()
        )
        assert len(events) == 1
        assert events[0].from_state == "open"
        assert events[0].to_state == "pending_review"

    def test_repeated_same_status_is_idempotent(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        assert repo.set_case_status(case, CaseStatus.PENDING_REVIEW) is True
        assert repo.set_case_status(case, CaseStatus.PENDING_REVIEW) is False

    def test_closed_case_cannot_be_reopened(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        repo.set_case_status(case, CaseStatus.CLOSED)
        assert case.closed_at is not None
        with pytest.raises(ValidationRejected):
            repo.set_case_status(case, CaseStatus.OPEN)

    def test_stage_transition_validated(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        assert repo.set_stage(case, ConversationStage.DISAMBIGUATION) is True
        with pytest.raises(ValidationRejected):
            repo.set_stage(case, ConversationStage.RATING)


class TestServiceMode:
    def test_mode_starts_autonomous(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        assert conversation.service_mode == ServiceMode.AUTONOMOUS.value

    def test_takeover_bumps_mode_revision(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        before = conversation.mode_revision
        changed = repo.set_service_mode(conversation, ServiceMode.OPERATOR_ASSISTED)
        assert changed is True
        assert conversation.mode_revision == before + 1

    def test_repeated_takeover_is_noop(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        repo.set_service_mode(conversation, ServiceMode.OPERATOR_ASSISTED)
        revision = conversation.mode_revision
        assert repo.set_service_mode(conversation, ServiceMode.OPERATOR_ASSISTED) is False
        assert conversation.mode_revision == revision

    def test_resume_ai_is_independent_operation(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        repo.set_service_mode(conversation, ServiceMode.OPERATOR_ASSISTED)
        repo.set_service_mode(conversation, ServiceMode.AUTONOMOUS)
        assert conversation.service_mode == ServiceMode.AUTONOMOUS.value
        assert conversation.mode_revision == 2


class TestCaseFacts:
    def test_standard_seller_name_not_overwritten_by_none(
        self, repo: ConversationRepository
    ) -> None:
        """AC-19：缺少唯一匹配时标准名为空，但不得用空值抹掉已有值。"""

        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        repo.update_case_facts(
            case, seller_name_raw="星海数码", seller_name_standard="星海数码专营店"
        )
        repo.update_case_facts(case, seller_name_raw="星海数码（补充）")
        assert case.seller_name_raw == "星海数码（补充）"
        assert case.seller_name_standard == "星海数码专营店"

    def test_intents_and_emotion_persist(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        repo.update_case_facts(
            case,
            intents=["diagnosis", "refund"],
            emotion_level=EmotionLevel.ANGRY,
            missing_facts=["purchase_channel"],
            facts={"fault_type": "weak_suction"},
        )
        assert case.customer_intents_json == '["diagnosis", "refund"]'
        assert case.emotion_level == "angry"
        assert case.missing_facts_json == '["purchase_channel"]'

    def test_troubleshooting_not_resolved_by_default(self, repo: ConversationRepository) -> None:
        """未经用户确认不得记为已解决。"""

        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        assert case.troubleshooting_result == TroubleshootingResult.NOT_ATTEMPTED.value


class TestRating:
    def test_rating_rejects_out_of_range(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        for bad in (0, 6, -1):
            with pytest.raises(ValidationRejected):
                repo.set_rating(case, status=RatingStatus.SUBMITTED, rating=bad)

    def test_skip_leaves_rating_empty(self, repo: ConversationRepository) -> None:
        """AC-14：跳过时评分为空，不得填默认分。"""

        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        repo.set_rating(case, status=RatingStatus.SKIPPED)
        assert case.rating_status == RatingStatus.SKIPPED.value
        assert case.user_rating is None

    def test_valid_rating_persists(self, repo: ConversationRepository) -> None:
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        case, _ = repo.create_case_for_conversation(conversation)
        repo.set_rating(case, status=RatingStatus.SUBMITTED, rating=5)
        assert case.user_rating == 5
