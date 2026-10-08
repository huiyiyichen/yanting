"""写事务必须在响应发出**之前**提交（缺陷第 49 项回归）。

为什么需要这条用例：`TestClient` 会把整个 ASGI 应用跑完才把响应交还给调用方，
所以「写→立刻读」在测试里几乎总能看到新值——**这层测试看不到真实竞态**。
真实浏览器不同：它拿到 200 的那一刻就可能发出下一次请求，而 FastAPI 把带
`yield` 依赖的收尾（`get_session` 的 `session.commit()`）放在响应发送**之后**
执行（`fastapi/routing.py`：`await response(scope, receive, send)` 之后才退出
依赖的 `AsyncExitStack`）。

因此这里不测「间隔多久」，而是直接测**顺序不变量**：在 ASGI 收到
`http.response.start`（响应头即将交给客户端）的那一刻，用**另一个会话、另一条
连接**读库，必须已经能看到这次写入。

修复前该用例会失败（读到旧值）。真实故障：客服接管会话返回 200、库里
`service_mode` 已是 `operator_assisted`（`mode_revision=1`，审计事件同时落库），
而紧随其后的 `GET /api/support/queue` 返回的响应体与接管前**逐字节相同**
（10186 字节），前端据此仍显示「AI 托管中」并保持输入框禁用。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.domain.case_state.models import Base as CaseBase
from app.domain.case_state.models import ConversationRow
from app.knowledge.models import Base as KnowledgeBase

CUSTOMER = {"X-Demo-View-Role": "customer"}
SUPPORT = {"X-Demo-View-Role": "support"}


class _ObserveBeforeResponseStart:
    """纯 ASGI 包装：在响应头转发给客户端之前执行一次观察。"""

    def __init__(
        self,
        app: Callable[..., Any],
        observe: Callable[[], dict[str, Any]],
        snapshots: list[dict[str, Any]],
    ) -> None:
        self.app = app
        self.observe = observe
        self.snapshots = snapshots

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict[str, Any]) -> None:
            # `http.response.start` 是「即将把响应交给客户端」的分界点：
            # 此刻必须已经能在另一条连接上读到本次写入。
            if message["type"] == "http.response.start":
                self.snapshots.append(self.observe())
            await send(message)

        await self.app(scope, receive, send_wrapper)


@dataclass
class Observed:
    client: TestClient
    #: 每次「响应头发出前」那一刻，另一条连接读到的库状态（按请求顺序）
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    #: 需要按 id 观察的会话（接管类用例在请求前设置）
    target_conversation_id: str | None = None

    @property
    def at_response_start(self) -> dict[str, Any]:
        """最近一次响应头阶段读到的库状态。"""

        assert self.snapshots, "没有任何请求经过观察点"
        return self.snapshots[-1]


@pytest.fixture
def observed(tmp_path: Path) -> Iterator[Observed]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.integrations.embedding_provider import MockEmbeddingProvider
    from app.integrations.model_provider import MockModelProvider
    from app.main import create_app
    from app.runtime import RuntimeContext
    from app.tools.registry import build_default_registry

    db_path = tmp_path / "commit.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    CaseBase.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    context = RuntimeContext(
        settings=Settings(),
        engine=engine,
        session_factory=factory,
        model_provider=MockModelProvider(responses=[]),
        embedding_provider=MockEmbeddingProvider(reason="提交时序测试"),
        tool_registry=build_default_registry(),
    )

    app = create_app()

    @asynccontextmanager
    async def _lifespan(_app: Any):  # type: ignore[no-untyped-def]
        _app.state.runtime = context
        yield
        context.close()

    app.router.lifespan_context = _lifespan

    holder = Observed(client=None)  # type: ignore[arg-type]

    def observe() -> dict[str, Any]:
        """用**独立会话**读库：拿到的只能是已提交的值。"""

        session = factory()
        try:
            snapshot: dict[str, Any] = {
                "conversationCount": session.execute(
                    select(func.count()).select_from(ConversationRow)
                ).scalar_one()
            }
            if holder.target_conversation_id:
                snapshot["serviceMode"] = session.execute(
                    select(ConversationRow.service_mode).where(
                        ConversationRow.conversation_id == holder.target_conversation_id
                    )
                ).scalar_one_or_none()
            return snapshot
        finally:
            session.close()

    wrapped = _ObserveBeforeResponseStart(app, observe, holder.snapshots)
    with TestClient(wrapped) as client:
        holder.client = client
        yield holder
    engine.dispose()


def test_conversation_creation_is_committed_before_response(observed: Observed) -> None:
    """新建会话的写入必须在响应头发出前就对其它连接可见（第 26 项的时序根因）。"""

    created = observed.client.post("/api/customer/conversations", json={}, headers=CUSTOMER)
    assert created.status_code == 200

    # 观察发生在响应头阶段：这里读到的就是客户端「拿到 200 的同一时刻」库里的状态
    assert observed.at_response_start["conversationCount"] == 1


def test_takeover_is_committed_before_response(observed: Observed) -> None:
    """接管写入必须在响应头发出前可见（第 49 项的真实故障场景）。"""

    created = observed.client.post("/api/customer/conversations", json={}, headers=CUSTOMER)
    assert created.status_code == 200
    conversation_id = created.json()["conversationId"]
    observed.target_conversation_id = conversation_id

    takeover = observed.client.post(
        f"/api/support/conversations/{conversation_id}/service-mode",
        json={"mode": "operator_assisted"},
        headers=SUPPORT,
    )
    assert takeover.status_code == 200
    assert takeover.json()["serviceMode"] == "operator_assisted"

    # 关键断言：响应头都还没发出去，另一条连接就必须读到 operator_assisted
    assert observed.at_response_start["serviceMode"] == "operator_assisted"


def test_support_send_requires_committed_flag_in_same_request(observed: Observed) -> None:
    """客服消息与接管状态在同一次请求里读取时不能互相看不见（无半写）。"""

    created = observed.client.post("/api/customer/conversations", json={}, headers=CUSTOMER)
    conversation_id = created.json()["conversationId"]
    observed.target_conversation_id = conversation_id

    # 新会话自带一条服务方开场白（固定文案），它是**创建时**写入的，不是这次拒绝写的
    before = observed.client.get(
        f"/api/support/conversations/{conversation_id}/messages", headers=SUPPORT
    ).json()
    assert [item["senderRole"] for item in before] == ["assistant"]

    # 托管期间发送被拒绝（409）：拒绝路径不得留下任何写入
    rejected = observed.client.post(
        f"/api/support/conversations/{conversation_id}/messages",
        json={"body": "未接管不应发出", "clientMessageKey": "commit-1"},
        headers=SUPPORT,
    )
    assert rejected.status_code == 409

    messages = observed.client.get(
        f"/api/support/conversations/{conversation_id}/messages", headers=SUPPORT
    )
    assert messages.status_code == 200
    # 消息数不变，且没有任何 operator 消息落库（拒绝路径无半写）
    after = messages.json()
    assert len(after) == len(before)
    assert all(item["senderRole"] != "operator" for item in after)
