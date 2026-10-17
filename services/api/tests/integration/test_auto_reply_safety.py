"""多 Agent 阶段 0 · S1：未通过核验的正文不得发给消费者。

失败方式：
F1 核验未通过（verification_status != verified）时，已生成正文被当作转人工过渡语插入会话。
F2 引用校验失败（validate_auto_reply 抛错）时，同样把正文作为过渡语发出。
F3 validate_auto_reply 传入 claims 时提前返回，禁用承诺/执行类正则不再生效。
F4 转人工后消费者侧收不到任何说明（应只收到固定的系统转人工提示）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from tests.integration import test_reception_workspace as fixtures
from tests.integration.test_auto_reception import jobs, replies

from app.domain.consumer_service import assistant as assistant_module
from app.domain.consumer_service.auto_reception import process_job, validate_auto_reply
from app.errors import ModelOutputInvalid

workspace = fixtures.workspace
CUSTOMER = fixtures.CUSTOMER
DRAFT = "亲，退款今天一定到账，请放心。"


def _fake_assistant(verification_status: str, claims=None):
    reply = SimpleNamespace(style="recommended", body=DRAFT, claims=claims)

    class Fake:
        def __init__(self, *args, **kwargs):
            pass

        def build(self, *args, **kwargs):
            return SimpleNamespace(
                is_mock=True, verification_status=verification_status,
                reply_suggestions=[reply], grounding_sources=[], knowledge_status="ready",
                handoff_required=False, intent="other", input_hash="h",
            )

    return Fake


@pytest.mark.parametrize("status", ["unverified", "failed"])
def test_unverified_draft_never_reaches_consumer(workspace, monkeypatch, status):
    client, factory, _provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "咨询物流")
    baseline = len(replies(client, cid))
    monkeypatch.setattr(assistant_module, "ConsumerServiceAssistant", _fake_assistant(status))
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    assert jobs(factory, cid)[0].status == "handoff"
    messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert not any(DRAFT in (m.get("body") or "") for m in messages)
    assert len(replies(client, cid)) == baseline
    assert messages[-1]["body"] == "已转人工，客服将继续跟进。"


def test_claims_failure_never_reaches_consumer(workspace, monkeypatch):
    client, factory, _provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "咨询物流")
    fake = _fake_assistant("verified", claims=[])
    monkeypatch.setattr(assistant_module, "ConsumerServiceAssistant", fake)
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    messages = client.get(f"/api/customer/conversations/{cid}/messages", headers=CUSTOMER).json()
    assert not any(DRAFT in (m.get("body") or "") for m in messages)


def test_forbidden_patterns_apply_even_with_claims():
    context = SimpleNamespace(orders=[], after_sales=[], tickets=[])
    with pytest.raises(ModelOutputInvalid):
        validate_auto_reply("已为您退款，请查收。", context, claims=[], sources=[])
