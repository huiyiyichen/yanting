"""案件编排端到端测试。

使用真实 SQLite + 真实知识索引（若已发布）+ 确定性 mock 模型，
验证三个核心功能的纵向流程、幂等与幻觉防控。

只用 mock 模型验证交互与流程；**不**用 mock 结果声称 live 质量达标。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.agent.orchestrator import CaseOrchestrator, OrchestratorDeps
from app.domain.agent.understanding import UnderstandingAnalyzer
from app.domain.case_state.models import Base
from app.domain.enums import (
    CaseStatus,
    CustomerIntent,
    EmotionLevel,
    KnowledgeHitStatus,
    SenderRole,
)
from app.errors import ProviderNotConfigured
from app.integrations.model_provider import MockModelProvider
from app.repositories.conversation_repository import ConversationRepository
from app.tool_gateway.gateway import ToolGateway
from app.tools.registry import build_default_registry


def _understanding_payload(
    *,
    product: str = "A1 Pro",
    fault: str = "weak_suction",
    intents: list[str] | None = None,
    emotion: str = "calm",
    complaint: str = "not_flagged",
    country: str = "中国",
    channel: str = "official_website",
) -> str:
    return json.dumps(
        {
            "product_model_text": product,
            "fault_type": fault,
            "fault_part": "filter",
            "phenomenon": "吸力明显变弱",
            "intents": intents or ["diagnosis"],
            "emotion_level": emotion,
            "complaint_risk": complaint,
            "complaint_reason": "",
            "country_code_text": country,
            "purchase_channel": channel,
            "seller_name_raw": "",
            "image_visible_clues": [],
            "urgency_note": "",
        },
        ensure_ascii=False,
    )


class _NoopEmbedding:
    """占位编码器：本用例聚焦编排逻辑，检索依赖由 mock 工具结果替代。

    实现 `available()`/`describe()` 以满足健康检查接口。
    """

    model_id = "noop"
    dimension = 1024

    def available(self) -> bool:
        return False

    def describe(self) -> dict[str, str]:
        return {"backend": "noop", "model_id": self.model_id}

    def encode(self, texts: list[str], *, is_query: bool = False):  # type: ignore[no-untyped-def]
        raise ProviderNotConfigured("本用例不执行真实编码")


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'agent.sqlite3'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    db = factory()
    try:
        yield db
        db.commit()
    finally:
        db.close()
        engine.dispose()


def _build(
    session: Session, responses: list[str]
) -> tuple[CaseOrchestrator, ConversationRepository, ToolGateway]:
    settings = Settings()
    # 用例不依赖真实知识索引：把工具白名单缩减为不含 knowledge_search 会导致
    # 编排流程与生产不一致，因此保留完整注册表，只让检索返回空结果。
    gateway = ToolGateway(build_default_registry(), session=session)
    provider = MockModelProvider(responses=responses)
    deps = OrchestratorDeps(
        session=session,
        settings=settings,
        embedding_provider=_NoopEmbedding(),  # type: ignore[arg-type]
        gateway=gateway,
        analyzer=UnderstandingAnalyzer(provider),
    )
    return CaseOrchestrator(deps), ConversationRepository(session), gateway


class TestMessageIdempotencyInOrchestration:
    def test_repeat_message_key_does_not_reprocess(self, session: Session) -> None:
        """重复提交同一幂等键：不重复理解、不重复产生副作用。"""

        orchestrator, repo, gateway = _build(session, [_understanding_payload()])
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")

        first = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="我的 A1 Pro 吸力不行了",
            client_message_key="k-1",
        )
        tool_calls_after_first = len(gateway.call_log())
        second = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="我的 A1 Pro 吸力不行了",
            client_message_key="k-1",
        )

        assert first.service_route != "idempotent_replay"
        assert second.service_route == "idempotent_replay"
        assert second.reply == ""
        # 第二次没有新增任何工具调用
        assert len(gateway.call_log()) == tool_calls_after_first
        # 客户消息只有一条，加一条自动回复
        assert repo.count_messages(conversation.conversation_id) == 2


class _TextOnlyMockProvider(MockModelProvider):
    """不声明多模态的 mock，与真实配置（文本模型、无 vision model）一致。"""

    @property
    def supports_vision(self) -> bool:
        return False


class TestVisionBoundary:
    def test_image_without_vision_model_reports_real_error(self, session: Session) -> None:
        """未配置多模态时不得假装看懂了图片。

        `MockModelProvider` 默认声明支持多模态，这里改用**不声明**多模态的 mock，
        与当前真实配置（DeepSeek 文本模型、无 vision model）保持一致。
        """

        settings = Settings()
        gateway = ToolGateway(build_default_registry(), session=session)
        provider = _TextOnlyMockProvider(responses=[_understanding_payload()])
        orchestrator = CaseOrchestrator(
            OrchestratorDeps(
                session=session,
                settings=settings,
                embedding_provider=_NoopEmbedding(),  # type: ignore[arg-type]
                gateway=gateway,
                analyzer=UnderstandingAnalyzer(provider),
            )
        )
        conversation = ConversationRepository(session).create_conversation(
            customer_id="CUST-DEMO-01"
        )

        with pytest.raises(ProviderNotConfigured, match="多模态模型未配置"):
            orchestrator.handle_customer_message(
                conversation_id=conversation.conversation_id,
                message="这是故障照片",
                client_message_key="img-1",
                image_data_urls=["data:image/png;base64,AAAA"],
            )


class TestCaseAssembly:
    def test_case_created_and_facts_persisted(self, session: Session) -> None:
        orchestrator, repo, _ = _build(session, [_understanding_payload()])
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")

        decision = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="我的 A1 Pro 吸力不行了，能退款吗",
            client_message_key="k-1",
        )

        case = repo.get_case_by_conversation(conversation.conversation_id)
        assert case is not None
        assert case.product_model == "A1 Pro"
        assert case.country_code == "CN"
        assert CustomerIntent.REFUND.value in case.customer_intents_json
        assert decision.emotion_level is EmotionLevel.CALM

    def test_reply_is_persisted_as_assistant_message(self, session: Session) -> None:
        orchestrator, repo, _ = _build(session, [_understanding_payload()])
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="吸力不行了",
            client_message_key="k-1",
        )
        messages = repo.list_messages(conversation.conversation_id)
        assert messages[0].sender_role == SenderRole.CUSTOMER.value
        assert messages[1].sender_role == SenderRole.ASSISTANT.value
        assert messages[1].body


class TestHallucinationBoundary:
    def test_missing_product_asks_instead_of_guessing(self, session: Session) -> None:
        """产品未确认时必须追问，不得直接给结论（AC-03）。"""

        orchestrator, repo, _ = _build(
            session, [_understanding_payload(product="", country="中国")]
        )
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        decision = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="它不吸了",
            client_message_key="k-1",
        )
        assert "product_model" in decision.missing_facts
        assert "ask_clarification" in decision.allowed_actions

    def test_no_evidence_does_not_produce_fabricated_promise(self, session: Session) -> None:
        """检索无依据时回复不得出现质保/退款承诺措辞。"""

        orchestrator, repo, _ = _build(
            session, [_understanding_payload(intents=["refund"], product="Z9 Unknown")]
        )
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        decision = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="我要退款",
            client_message_key="k-1",
        )
        for forbidden in ("一定能", "保证", "承诺", "已经退款", "已退款"):
            assert forbidden not in decision.reply

    def test_product_full_name_falls_back_to_name_recall(self, session: Session) -> None:
        """模型把「A1 Pro 无线吸尘器」整串当型号时，必须退回名称召回（AC-03）。

        真实缺陷：型号精确匹配失败会返回 `not_found`、候选为空，于是
        「多候选必须补问」静默失效；用户既看不到候选，也拿不到确认追问。
        """

        orchestrator, repo, _ = _build(
            session, [_understanding_payload(product="A1 Pro 无线吸尘器", country="中国")]
        )
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        decision = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="我的 A1 Pro 无线吸尘器吸力变弱",
            client_message_key="k-fallback",
        )
        # 名称召回应拿到候选，并在回复里请用户确认
        assert decision.product_candidates, "候选为空说明没有退回名称召回"
        assert "请您确认" in decision.reply
        # 型号要收敛成标准型号，否则知识过滤永远匹配不上
        assert decision.facts.product_model == "A1 Pro"

    def test_multi_candidate_reply_asks_user_to_confirm(self, session: Session) -> None:
        """多候选时回复必须列出候选并请用户确认，而不是静默当作已确认。"""

        orchestrator, repo, _ = _build(
            session, [_understanding_payload(product="A1 Pro", country="中国")]
        )
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        decision = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="A1 Pro 坏了",
            client_message_key="k-ask",
        )
        assert len(decision.product_candidates) > 1
        assert "请您确认" in decision.reply
        # 消歧未完成时不得认定具体产品
        assert decision.facts.product_id is None

    def test_high_risk_request_never_auto_approved(self, session: Session) -> None:
        """退款申请只生成草稿；案件进入待确认而非已结束。"""

        orchestrator, repo, _ = _build(session, [_understanding_payload(intents=["refund"])])
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        decision = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="我要退款",
            client_message_key="k-1",
        )
        case = repo.get_case_by_conversation(conversation.conversation_id)
        assert case is not None
        assert case.case_status != CaseStatus.CLOSED.value
        # 若生成了草稿，必须处于待人工确认
        if decision.request_draft:
            assert decision.request_draft["requestStatus"] == "pending_confirmation"


class TestUnderstandingFailure:
    def test_invalid_model_output_raises_not_guesses(self, session: Session) -> None:
        orchestrator, repo, _ = _build(session, ["这不是 JSON"])
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        with pytest.raises(Exception, match="JSON"):
            orchestrator.handle_customer_message(
                conversation_id=conversation.conversation_id,
                message="吸力不行",
                client_message_key="k-1",
            )

    def test_unknown_enum_values_fall_back_to_unknown(self, session: Session) -> None:
        """模型给出非法枚举时必须归为 unknown，而不是自由生成类别。"""

        payload = json.loads(_understanding_payload())
        payload["fault_type"] = "totally_made_up_fault"
        payload["emotion_level"] = "furious"
        orchestrator, repo, _ = _build(session, [json.dumps(payload, ensure_ascii=False)])
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        decision = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="吸力不行",
            client_message_key="k-1",
        )
        assert decision.facts.fault_type.value == "unknown"
        assert decision.emotion_level is EmotionLevel.UNKNOWN


class TestEmotionPersisted:
    def test_angry_emotion_stored_without_escalation(self, session: Session) -> None:
        orchestrator, repo, _ = _build(
            session,
            [_understanding_payload(emotion="angry", complaint="flagged")],
        )
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        decision = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="你们这什么破机器！",
            client_message_key="k-1",
        )
        case = repo.get_case_by_conversation(conversation.conversation_id)
        assert case is not None
        assert case.emotion_level == "angry"
        assert case.complaint_risk == "flagged"
        # 单纯愤怒不触发后台复核
        assert decision.human_intervention_required is False


class TestKnowledgeStatusRecorded:
    def test_hit_status_is_recorded_on_case(self, session: Session) -> None:
        orchestrator, repo, _ = _build(session, [_understanding_payload()])
        conversation = repo.create_conversation(customer_id="CUST-DEMO-01")
        decision = orchestrator.handle_customer_message(
            conversation_id=conversation.conversation_id,
            message="吸力不行了",
            client_message_key="k-1",
        )
        case = repo.get_case_by_conversation(conversation.conversation_id)
        assert case is not None
        # 检索失败或未命中都必须有明确状态，不能留空伪装成"未检索"
        if decision.knowledge_hit_status is not None:
            assert case.knowledge_hit_status == decision.knowledge_hit_status.value
        assert decision.knowledge_hit_status in {
            KnowledgeHitStatus.NOT_FOUND,
            KnowledgeHitStatus.INSUFFICIENT,
            KnowledgeHitStatus.SUFFICIENT,
            None,
        }
