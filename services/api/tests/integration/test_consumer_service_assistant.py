from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.domain.case_state.models import Base as CaseBase
from app.domain.consumer_service import models as _consumer_models  # noqa: F401
from app.domain.consumer_service.importer import import_business_workbook
from app.integrations.embedding_provider import MockEmbeddingProvider
from app.integrations.model_provider import (
    ChatResult,
    ModelProvider,
    OpenAICompatibleModelProvider,
)
from app.knowledge.models import Base as KnowledgeBase
from app.main import create_app
from app.runtime import RuntimeContext
from app.tools.registry import build_default_registry

OFFICIAL_SOURCE = Path(r"D:\下载\赛题 1：数据共情者-业务数据.xlsx")
SUPPORT = {"X-Demo-View-Role": "support"}


class _AssistantProvider:
    model_id = "loreal-test-model"
    supports_vision = False

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def available(self) -> bool:
        return True

    def complete(self, messages: list[Any], **_: Any) -> ChatResult:
        assert messages[0].role == "system"
        return ChatResult(
            text=json.dumps(
                {"supported": True, "issues": []} if messages[0].content.startswith("GROUNDING_REVIEW_V1")
                else self.payload, ensure_ascii=False,
            ),
            model=self.model_id,
            latency_seconds=0.01,
            is_mock=True,
        )


def _client(tmp_path: Path, provider: ModelProvider) -> TestClient:
    engine = build_engine(
        Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'assistant.sqlite3'}")
    )
    CaseBase.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = build_session_factory(engine)
    session = factory()
    import_business_workbook(session, OFFICIAL_SOURCE, repo_root=tmp_path)
    session.commit()
    session.close()

    context = RuntimeContext(
        settings=Settings(),
        engine=engine,
        session_factory=factory,
        model_provider=provider,
        embedding_provider=MockEmbeddingProvider(reason="客服辅助测试"),
        tool_registry=build_default_registry(),
    )
    app = create_app()

    @asynccontextmanager
    async def lifespan(_app: Any):
        _app.state.runtime = context
        yield
        context.close()

    app.router.lifespan_context = lifespan
    return TestClient(app)


def test_assistant_uses_model_and_rule_risk(tmp_path: Path) -> None:
    provider = _AssistantProvider(
        {
            "current_question": "消费者反馈使用后皮肤不适",
            "service_summary": "消费者反馈使用商品后出现不适，已有不良反应工单。",
            "emotion_level": "dissatisfied",
            "missing_information": ["使用时间"],
            "next_steps": ["核对不良反应工单", "由客服人工跟进"],
            "reply_suggestions": [
                {
                    "style": "recommended",
                    "body": "抱歉给您带来不适，我先核对已有服务记录，再请客服继续跟进。",
                }
            ],
        }
    )
    client = _client(tmp_path, provider)
    with client:
        before = client.get(
            "/api/support/conversations/S00082/service-context",
            headers=SUPPORT,
        ).json()["timeline"]
        response = client.post(
            "/api/support/reception/S00082/assistant",
            headers=SUPPORT,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["isMock"] is True
        assert payload["emotionLevel"] == "dissatisfied"
        assert payload["riskTypes"] == ["adverse_reaction"]
        assert payload["riskLevel"] == "high"
        assert payload["riskStatus"] == "pending"
        assert payload["replySuggestions"][0]["style"] == "recommended"
        after = client.get(
            "/api/support/conversations/S00082/service-context",
            headers=SUPPORT,
        ).json()["timeline"]
        assert len(after) == len(before)

        audit = client.get("/api/support/audit/S00082", headers=SUPPORT)
        assert audit.status_code == 200
        assert {item["eventType"] for item in audit.json()} >= {
            "model_call",
            "consumer_assistant_generated",
        }


def test_assistant_does_not_succeed_without_model(tmp_path: Path) -> None:
    provider = OpenAICompatibleModelProvider(
        base_url="",
        api_key="",
        model="",
    )
    client = _client(tmp_path, provider)
    with client:
        response = client.post(
            "/api/support/reception/S00082/assistant",
            headers=SUPPORT,
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "provider_not_configured"
