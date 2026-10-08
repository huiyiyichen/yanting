"""审计写入测试。

覆盖 PRD 第 4.6 节与工程规范第 7 节：
- 关键字段齐全（trace_id / 模型 / 提示词版本 / 工具 / 风险 / 确认状态）；
- **不保存完整原始 prompt/output**，只保存哈希与脱敏摘要；
- 手机号、订单号等必须掩码；
- 审计事件**追加**，不被业务状态覆盖；
- 不存在任何人工超时事件。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.recorder import (
    AuditContext,
    AuditRecorder,
    audit_event_payload,
    hash_text,
    mask_sensitive,
    summarize,
)
from app.domain.case_state.models import AuditEventRow, Base


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'audit.sqlite3'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = factory()
    try:
        yield db
        db.commit()
    finally:
        db.close()
        engine.dispose()


class TestMasking:
    def test_phone_is_masked(self) -> None:
        assert "13800138000" not in mask_sensitive("联系我 13800138000 谢谢")

    def test_order_number_is_masked(self) -> None:
        masked = mask_sensitive("订单 SO-2026-123456 已提交")
        assert "SO-2026-123456" not in masked

    def test_email_is_masked(self) -> None:
        assert "user@example.com" not in mask_sensitive("邮箱 user@example.com")

    def test_id_card_is_masked(self) -> None:
        assert "110101199001011234" not in mask_sensitive("证件 110101199001011234")

    def test_normal_text_unchanged(self) -> None:
        text = "吸尘器吸力变弱，滤网已清洗"
        assert mask_sensitive(text) == text

    def test_summarize_truncates_after_masking(self) -> None:
        long_text = "手机 13800138000 " + "故障描述" * 50
        result = summarize(long_text, limit=40)
        assert len(result) <= 40
        assert "13800138000" not in result


class TestHashPolicy:
    def test_hash_is_stable_and_not_reversible(self) -> None:
        text = "我的订单号是 SO-2026-123456"
        digest = hash_text(text)
        assert digest == hash_text(text)
        assert "SO-2026" not in digest
        assert len(digest) == 64


class TestAuditRecording:
    def test_record_persists_required_fields(self, session: Session) -> None:
        recorder = AuditRecorder(session)
        context = AuditContext.new_turn(
            actor_type="agent",
            conversation_id="conv-1",
            case_id="case-1",
            model_name="mock-model",
            prompt_version="s2-understanding-v1",
            output_schema_version="understanding.v1",
        )
        row = recorder.record(
            context,
            event_type="model_call",
            input_text="用户原始消息",
            knowledge_snapshot_version="snap-1",
        )
        session.commit()

        stored = session.get(AuditEventRow, row.audit_event_id)
        assert stored is not None
        assert stored.trace_id == context.trace_id
        assert stored.conversation_id == "conv-1"
        assert stored.case_id == "case-1"
        assert stored.actor_type == "agent"
        assert stored.model_name == "mock-model"
        assert stored.prompt_version == "s2-understanding-v1"
        assert stored.output_schema_version == "understanding.v1"
        assert stored.knowledge_snapshot_version == "snap-1"
        assert stored.input_hash == hash_text("用户原始消息")
        assert stored.created_at is not None

    def test_raw_input_is_not_stored(self, session: Session) -> None:
        """审计不得保存完整原始输入。"""

        recorder = AuditRecorder(session)
        context = AuditContext.new_turn(actor_type="customer", conversation_id="conv-1")
        secret = "我的手机号是 13800138000，订单 SO-2026-999888"
        row = recorder.record(context, event_type="model_call", input_text=secret)
        session.commit()

        stored = session.get(AuditEventRow, row.audit_event_id)
        assert stored is not None
        serialized = f"{stored.input_hash}{stored.detail_json}{stored.tool_name or ''}"
        assert "13800138000" not in serialized
        assert "SO-2026-999888" not in serialized
        assert secret not in serialized

    def test_detail_is_json_serializable(self, session: Session) -> None:
        import json

        recorder = AuditRecorder(session)
        context = AuditContext.new_turn(actor_type="agent")
        row = recorder.record(
            context,
            event_type="agent_decision",
            detail={"serviceRoute": "troubleshooting", "count": 2, "nested": {"a": [1, 2]}},
        )
        session.commit()
        parsed = json.loads(row.detail_json)
        assert parsed["serviceRoute"] == "troubleshooting"
        assert parsed["nested"]["a"] == [1, 2]


class TestToolCallAudit:
    def test_each_tool_call_becomes_one_event(self, session: Session) -> None:
        recorder = AuditRecorder(session)
        context = AuditContext.new_turn(actor_type="agent", case_id="case-1")
        written = recorder.record_tool_calls(
            context,
            call_log=[
                {
                    "tool": "knowledge_search",
                    "status": "ok",
                    "riskLevel": "read_only",
                    "toolRequestId": "treq-1",
                    "arguments": {"query": "吸力弱"},
                    "message": "命中 5 条证据",
                },
                {
                    "tool": "order_lookup",
                    "status": "not_found",
                    "riskLevel": "read_only",
                    "toolRequestId": "treq-2",
                    "arguments": {},
                    "message": "订单未命中",
                },
            ],
        )
        session.commit()
        assert written == 2
        rows = list(session.execute(select(AuditEventRow)).scalars())
        assert len(rows) == 2
        statuses = {row.tool_status for row in rows}
        assert statuses == {"ok", "not_found"}
        assert all(row.tool_request_id for row in rows)

    def test_failed_tool_is_audited(self, session: Session) -> None:
        """工具失败/超时同样必须记录（工程规范第 7 节）。"""

        recorder = AuditRecorder(session)
        context = AuditContext.new_turn(actor_type="agent")
        recorder.record_tool_calls(
            context,
            call_log=[
                {
                    "tool": "knowledge_search",
                    "status": "failed",
                    "riskLevel": "read_only",
                    "toolRequestId": "treq-x",
                    "message": "缺少依赖",
                }
            ],
        )
        session.commit()
        row = session.execute(select(AuditEventRow)).scalars().first()
        assert row is not None
        assert row.tool_status == "failed"


class TestAppendOnly:
    def test_events_are_never_overwritten(self, session: Session) -> None:
        """同一 trace 下多次记录产生多条事件，不互相覆盖。"""

        recorder = AuditRecorder(session)
        context = AuditContext.new_turn(actor_type="agent", case_id="case-1")
        for index in range(3):
            recorder.record(context, event_type="tool_call", tool_name=f"tool_{index}")
        session.commit()
        rows = list(session.execute(select(AuditEventRow)).scalars())
        assert len(rows) == 3
        assert {row.tool_name for row in rows} == {"tool_0", "tool_1", "tool_2"}
        assert all(row.trace_id == context.trace_id for row in rows)


class TestNoTimeoutEvents:
    def test_no_timeout_event_types_exist(self, session: Session) -> None:
        """本期不存在人工超时，也不应生成超时事件。"""

        recorder = AuditRecorder(session)
        context = AuditContext.new_turn(actor_type="system")
        recorder.record(context, event_type="agent_decision")
        session.commit()
        rows = list(session.execute(select(AuditEventRow)).scalars())
        for row in rows:
            assert "timeout" not in row.event_type
            assert "escalat" not in row.event_type


class TestHumanReviewAudit:
    def test_review_event_carries_version_and_action(self, session: Session) -> None:
        recorder = AuditRecorder(session)
        context = AuditContext.new_turn(
            actor_type="operator", conversation_id="conv-9", case_id="case-9"
        )
        row = recorder.record(
            context,
            event_type="human_review",
            risk_level="request_creation",
            human_confirmation_status="approved",
            detail={
                "requestId": "req-1",
                "action": "approve",
                "fromStatus": "pending_confirmation",
                "toStatus": "approved",
                "requestRevision": 1,
                "payloadHash": "abc",
            },
        )
        session.commit()
        assert row.actor_type == "operator"
        assert row.human_confirmation_status == "approved"
        assert row.risk_level == "request_creation"
        assert "req-1" in row.detail_json


class TestAuditPayload:
    def test_payload_excludes_detail_body(self, session: Session) -> None:
        """对外结构只给索引字段，不含 detail 原文。"""

        recorder = AuditRecorder(session)
        context = AuditContext.new_turn(actor_type="agent", conversation_id="conv-1")
        row = recorder.record(
            context,
            event_type="agent_decision",
            detail={"replySummary": "这是回复摘要"},
        )
        session.commit()
        payload = audit_event_payload(row)
        assert payload["traceId"] == context.trace_id
        assert payload["eventType"] == "agent_decision"
        assert "detail" not in payload
        assert "replySummary" not in str(payload)
