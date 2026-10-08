"""多模态链路：模型看到的图片线索必须被用起来（回复里说出来 + 客服可核对）。

背景（实测）：配置了多模态模型之后，客户端上传的面板照片确实被看懂了——
案件事实里出现 `observedFromImage: ["面板上有POWER和FILTER两个指示灯，
POWER指示灯显示为红色，FILTER指示灯显示为绿色", "面板上印有序列号文字S/N 8842-XR"]`。
但**回复里一个字都没提**：客户问「照片里两个指示灯分别是什么状态、序列号多少」，
拿到的仍是通用排障步骤。等于看图能力白做，用户也无从知道图被看过了。

因此这里固定两条不变量：
1. 有图片可见线索时，回复必须复述可见现象（并明确是「看了照片」）；
2. 客服案件视图必须能读到 `observedFromImage`，否则无法核对模型看没看对。

本用例用脚本化模型（声明支持多模态），不调用真实模型；真实链路另有 live 记录。
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
SUPPORT = {"X-Demo-View-Role": "support"}


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


UNDERSTANDING_WITH_CLUES = json.dumps(
    {
        "product_model_text": "",
        "fault_type": "unknown",
        "fault_part": "unknown",
        "phenomenon": "客户拍摄了机器面板照片，询问指示灯状态与序列号",
        "intents": ["diagnosis"],
        "emotion_level": "calm",
        "complaint_risk": "not_flagged",
        "complaint_reason": "",
        "country_code_text": "",
        "purchase_channel": "unknown",
        "seller_name_raw": "",
        "image_visible_clues": [
            "面板上有 POWER 与 FILTER 两个指示灯，POWER 为红色、FILTER 为绿色",
            "面板上印有序列号 S/N 8842-XR",
        ],
        "urgency_note": "",
    },
    ensure_ascii=False,
)


class _VisionScriptedProvider:
    """声明支持多模态的脚本化模型：只回一条理解结果。"""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[Any]] = []

    @property
    def model_id(self) -> str:
        return "scripted-vision"

    @property
    def supports_vision(self) -> bool:
        return True

    def available(self) -> bool:
        return True

    #: 回复生成的用户提示词里一定会出现这句话（见 app/domain/agent/reply.py）
    REPLY_MARKER = "请直接输出给客户的回复正文"

    def complete(self, messages: list[Any], **_: Any) -> Any:
        """同一个提供者既做理解也做回复（与生产一致），因此要按提示词区分。"""

        from app.integrations.model_provider import ChatResult

        self.calls.append(list(messages))
        is_reply = any(
            self.REPLY_MARKER in str(getattr(message, "content", "")) for message in messages
        )
        if is_reply:
            # 桩模型「照读」提示词里的图片线索：真实模型就是这样把线索写进回复的，
            # 这样「线索有没有传给模型」才是可测的（固定句子测不出来）。
            prompt_text = "\n".join(str(getattr(message, "content", "")) for message in messages)
            marker = "图片可见线索："
            index = prompt_text.find(marker)
            clue = ""
            if index >= 0:
                # 线索与其它事实拼在同一行（「已知事实：产品型号：…；图片可见线索：…」），
                # 因此取标记之后到行尾的内容
                clue = prompt_text[index + len(marker) :].split("\n")[0].strip()
            if clue:
                return ChatResult(
                    text=f"我先看了您发的照片：{clue}。下面按资料里的步骤帮您确认。",
                    model=self.model_id,
                    latency_seconds=0.01,
                )
            return ChatResult(
                text="好的，我先按您描述的现象帮您排查，请按下面的步骤试一下。",
                model=self.model_id,
                latency_seconds=0.01,
            )
        text = self._responses.pop(0) if self._responses else "{}"
        return ChatResult(text=text, model=self.model_id, latency_seconds=0.01)


class _StubEmbedding:
    model_id = "stub"
    dimension = 1024

    def available(self) -> bool:
        return False

    def describe(self) -> dict[str, str]:
        return {"backend": "stub", "model_id": self.model_id}

    def encode(self, texts: list[str], *, is_query: bool = False) -> Any:
        raise RuntimeError("本用例不执行真实编码")


@pytest.fixture
def vision_client(tmp_path: Path) -> Iterator[tuple[TestClient, _VisionScriptedProvider]]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.main import create_app
    from app.runtime import RuntimeContext
    from app.tools.registry import build_default_registry

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'v.sqlite3'}", future=True)
    CaseBase.metadata.create_all(engine)
    KnowledgeBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    provider = _VisionScriptedProvider([UNDERSTANDING_WITH_CLUES] * 5)
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
    with TestClient(app) as test_client:
        yield test_client, provider
    engine.dispose()


def _send_with_image(client: TestClient, client_message_key: str = "vision-1") -> dict[str, Any]:
    conversation_id = client.post("/api/customer/conversations", json={}, headers=CUSTOMER).json()[
        "conversationId"
    ]
    uploaded = client.post(
        f"/api/customer/conversations/{conversation_id}/attachments",
        files={"file": ("panel.png", _png_bytes(), "image/png")},
        headers=CUSTOMER,
    )
    attachment_id = uploaded.json()["attachmentId"]
    sent = client.post(
        f"/api/customer/conversations/{conversation_id}/messages",
        json={
            "body": "这是我拍的机器面板照片，两个指示灯分别是什么状态？序列号是多少？",
            "clientMessageKey": client_message_key,
            "attachmentIds": [attachment_id],
        },
        headers=CUSTOMER,
    )
    assert sent.status_code == 200, sent.text
    return {"conversationId": conversation_id, "body": sent.json()}


def test_reply_mentions_what_the_model_saw(
    vision_client: tuple[TestClient, _VisionScriptedProvider],
) -> None:
    """有图片线索时，回复必须把「看到的」说出来，而不是只给通用步骤。"""

    client, _provider = vision_client
    result = _send_with_image(client)
    reply = result["body"]["reply"]["body"]

    assert "我先看了您发的照片" in reply
    assert "POWER" in reply and "FILTER" in reply
    assert "8842-XR" in reply


def test_image_clues_are_visible_to_support(
    vision_client: tuple[TestClient, _VisionScriptedProvider],
) -> None:
    """客服案件视图必须能读到图片线索，用于核对模型看没看对。"""

    client, _provider = vision_client
    result = _send_with_image(client, client_message_key="vision-2")

    case = client.get(
        f"/api/support/conversations/{result['conversationId']}/case", headers=SUPPORT
    )
    assert case.status_code == 200
    clues = case.json()["observedFromImage"]
    assert len(clues) == 2
    assert "POWER" in clues[0]
    assert "8842-XR" in clues[1]


def test_no_image_means_no_photo_sentence(
    vision_client: tuple[TestClient, _VisionScriptedProvider],
) -> None:
    """**没有带图**时，即使模型凭空给出可见线索，也绝不能声称「我看了照片」。

    这是防幻觉的一条硬边界：句子由「确实带了图」+「模型给出线索」两个条件共同决定。
    """

    client, _provider = vision_client
    conversation_id = client.post("/api/customer/conversations", json={}, headers=CUSTOMER).json()[
        "conversationId"
    ]
    # 故意不带 attachmentIds，而脚本化模型仍会返回含线索的理解结果
    sent = client.post(
        f"/api/customer/conversations/{conversation_id}/messages",
        json={
            "body": "吸力变弱了怎么办",
            "clientMessageKey": "vision-3",
        },
        headers=CUSTOMER,
    )
    assert sent.status_code == 200
    assert "我先看了您发的照片" not in sent.json()["reply"]["body"]


class TestHumanHandoverRequest:
    """「客户说到转接人工时，直接转接」——用户 2026-09-25 补充的规则。

    PRD 原本只写了「愤怒不直接转人工」以及若干「可转人工」的条件，
    没有「客户主动要求即转接」这条；因此这里固定住三条不变量：
    1. 命中即转接（服务模式变成客服接管）；
    2. 回复不留空、也不夸张（不承诺真人马上在线）；
    3. 留下审计（谁可以自动发言发生变更）。
    """

    @pytest.mark.parametrize(
        "text",
        ["我要转人工", "转接人工客服", "请让真人客服联系我", "能不能转客服处理"],
    )
    def test_explicit_request_triggers_handover(
        self, vision_client: tuple[TestClient, _VisionScriptedProvider], text: str
    ) -> None:
        client, _provider = vision_client
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=CUSTOMER
        ).json()["conversationId"]
        sent = client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={"body": text, "clientMessageKey": f"handover-{abs(hash(text)) % 100000}"},
            headers=CUSTOMER,
        )
        assert sent.status_code == 200, sent.text
        assert "已经为您转接人工客服" in sent.json()["reply"]["body"]

        # 服务模式真的变了：客服工作台的队列里能看到「客服已接管」
        queue = client.get("/api/support/queue", headers=SUPPORT).json()
        row = next(item for item in queue if item["conversationId"] == conversation_id)
        assert row["serviceMode"] == "operator_assisted"

    def test_unrelated_message_does_not_handover(
        self, vision_client: tuple[TestClient, _VisionScriptedProvider]
    ) -> None:
        """不能因为出现过「人工」两个字就误转接。"""

        client, _provider = vision_client
        conversation_id = client.post(
            "/api/customer/conversations", json={}, headers=CUSTOMER
        ).json()["conversationId"]
        client.post(
            f"/api/customer/conversations/{conversation_id}/messages",
            json={
                "body": "这台机器的滤芯能人工清洗吗？吸力变弱了",
                "clientMessageKey": "handover-negative",
            },
            headers=CUSTOMER,
        )
        queue = client.get("/api/support/queue", headers=SUPPORT).json()
        row = next(item for item in queue if item["conversationId"] == conversation_id)
        assert row["serviceMode"] == "autonomous"
