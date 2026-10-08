"""回复生成：模型优先、越界/失败回退模板（用户要求「对话要接通模型」）。

固定四条不变量：
1. 模型返回正常文本 → 用它作为客户可见回复；
2. 命中承诺类措辞（保证/一定能/已退款…）→ **作废并回退模板**；
3. 返回结构化 JSON（模型答错格式）→ 同样回退，不能让客户看到 JSON；
4. 模型调用报错 → 回退模板，绝不产生空回复。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.case_state.models import Base as CaseBase
from app.knowledge.models import Base as KnowledgeBase

CUSTOMER = {"X-Demo-View-Role": "customer"}

UNDERSTANDING = json.dumps(
    {
        "product_model_text": "A1 Pro",
        "fault_type": "weak_suction",
        "fault_part": "filter",
        "phenomenon": "吸力变弱",
        "intents": ["diagnosis"],
        "emotion_level": "calm",
        "complaint_risk": "not_flagged",
        "complaint_reason": "",
        "country_code_text": "中国",
        "purchase_channel": "official_website",
        "seller_name_raw": "",
        "image_visible_clues": [],
        "urgency_note": "",
    },
    ensure_ascii=False,
)

REPLY_MARKER = "请直接输出给客户的回复正文"


class _ReplyProvider:
    """理解调用返回固定 JSON；回复调用按脚本返回（或抛错）。"""

    def __init__(self, reply_text: str | None, *, raise_on_reply: bool = False) -> None:
        self._reply_text = reply_text
        self._raise = raise_on_reply
        self.reply_prompts: list[str] = []

    @property
    def model_id(self) -> str:
        return "stub-reply-model"

    @property
    def supports_vision(self) -> bool:
        return False

    def available(self) -> bool:
        return True

    def complete(self, messages: list[Any], **_: Any) -> Any:
        from app.integrations.model_provider import ChatResult

        is_reply = any(REPLY_MARKER in str(getattr(message, "content", "")) for message in messages)
        if not is_reply:
            return ChatResult(text=UNDERSTANDING, model=self.model_id, latency_seconds=0.01)
        if self._raise:
            raise RuntimeError("模拟模型服务不可用")
        prompt = next(
            str(getattr(message, "content", ""))
            for message in messages
            if REPLY_MARKER in str(getattr(message, "content", ""))
        )
        self.reply_prompts.append(prompt)
        return ChatResult(text=self._reply_text or "", model=self.model_id, latency_seconds=0.02)


class _StubEmbedding:
    model_id = "stub"
    dimension = 1024

    def available(self) -> bool:
        return False

    def describe(self) -> dict[str, str]:
        return {"backend": "stub", "model_id": self.model_id}

    def encode(self, texts: list[str], *, is_query: bool = False) -> Any:
        raise RuntimeError("本用例不执行真实编码")


def _make_client(tmp_path: Path, provider: _ReplyProvider) -> Iterator[TestClient]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.main import create_app
    from app.runtime import RuntimeContext
    from app.tools.registry import build_default_registry

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'r.sqlite3'}", future=True)
    from app.domain.platform import models as _platform_models  # noqa: F401

    CaseBase.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    context = RuntimeContext(
        settings=Settings(runtime_dir=str(tmp_path / "runtime")),
        engine=engine,
        session_factory=factory,
        model_provider=provider,
        embedding_provider=_StubEmbedding(),
        tool_registry=build_default_registry(),
    )

    app = create_app()

    @asynccontextmanager
    async def _lifespan(_app: Any):  # type: ignore[no-untyped-def]
        _app.state.runtime = context
        yield
        context.close()

    app.router.lifespan_context = _lifespan
    with TestClient(app) as client:
        yield client
    engine.dispose()


@pytest.fixture
def make_client(tmp_path: Path):
    created: list[Any] = []

    def _factory(provider: _ReplyProvider) -> TestClient:
        generator = _make_client(tmp_path, provider)
        client = next(generator)
        created.append(generator)
        return client

    yield _factory
    for generator in created:
        generator.close()


def _send(client: TestClient, body: str = "吸力变弱了怎么办") -> str:
    conversation_id = client.post("/api/customer/conversations", json={}, headers=CUSTOMER).json()[
        "conversationId"
    ]
    sent = client.post(
        f"/api/customer/conversations/{conversation_id}/messages",
        json={"body": body, "clientMessageKey": f"reply-{abs(hash(body)) % 100000}"},
        headers=CUSTOMER,
    )
    assert sent.status_code == 200, sent.text
    return sent.json()["reply"]["body"]


def test_model_reply_is_used(make_client: Any) -> None:
    provider = _ReplyProvider("您先检查一下滤芯是否积灰，清理后再试试；有问题随时找我。")
    reply = _send(make_client(provider))
    assert reply.startswith("您先检查一下滤芯")
    # 提示词里必须带上约束与「不许承诺」的要求
    assert provider.reply_prompts, "回复调用没有发生"
    assert "不要编造" in provider.reply_prompts[-1]


def test_promise_wording_falls_back_to_template(make_client: Any) -> None:
    provider = _ReplyProvider("我保证一周内一定给您退款，请放心。")
    reply = _send(make_client(provider))
    assert "保证" not in reply
    assert "退款" not in reply or "申请" in reply  # 模板口径：只能说申请与人工确认


def test_structured_output_falls_back_to_template(make_client: Any) -> None:
    provider = _ReplyProvider('{"phenomenon": "吸力变弱", "intents": ["diagnosis"]}')
    reply = _send(make_client(provider))
    assert not reply.startswith("{")
    assert "phenomenon" not in reply


def test_model_failure_falls_back_to_template_without_empty_reply(make_client: Any) -> None:
    provider = _ReplyProvider(None, raise_on_reply=True)
    reply = _send(make_client(provider))
    assert reply.strip(), "模型失败时不能出现空回复"
