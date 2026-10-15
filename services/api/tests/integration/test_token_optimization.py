"""P1-7 Token 优化：上下文去重、契约进固定前缀、结果复用。

失败方式：
F1 recentConversation 与 sourceCatalog 重复发送同一条消息原文；
F2 去重后，来源目录里没有的消息（如 AI 接待发言）丢了正文，模型看不到上下文；
F3 输出契约留在每次变化的用户负载里，系统前缀因会话不同而不同，前缀缓存失效；
F4 输入哈希未变时再次生成仍重跑全流程（重复计费）；
F5 指定风格重生成或输入已变化时错误地复用旧缓存。
"""

import json

from tests.integration import test_reception_workspace as fixtures
from tests.integration.test_grounded_workflow import make_provider

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT


def _draft_calls(provider):
    return [call for call in provider.calls if not call[0].content.startswith("GROUNDING_REVIEW_V1")]


def test_dialogue_references_catalog_messages_and_contract_lives_in_system_prefix(workspace):
    client, _, provider = workspace
    make_provider(provider, lambda _: json.loads(fixtures.OUTPUT))
    systems = []
    for text in ("帮我看看订单", "包装破损了怎么办"):
        cid = fixtures._create(client)
        fixtures._send(client, cid, text)
        response = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
        assert response.status_code == 200, response.text
        system, user = _draft_calls(provider)[-1][:2]
        payload = json.loads(user.content)
        catalog = {source["sourceId"]: source for source in payload["sourceCatalog"]}
        for entry in payload["recentConversation"]:
            if "sourceId" in entry:
                assert entry["sourceId"] in catalog and "body" not in entry
            else:
                assert entry["body"] and not any(s["text"] == entry["body"] for s in catalog.values())
        assert any("sourceId" in entry for entry in payload["recentConversation"])
        assert {"replyContract", "adviceContract", "claimFieldRules"}.isdisjoint(payload)
        contract = json.loads(system.content.split("OUTPUT_CONTRACT_V1\n", 1)[1])
        assert "segments" in contract["replyContract"]["properties"]
        systems.append(system.content)
    assert systems[0] == systems[1]


def test_unchanged_input_reuses_cached_result_without_model_calls(workspace):
    client, _, provider = workspace
    make_provider(provider, lambda _: json.loads(fixtures.OUTPUT))
    cid = fixtures._create(client)
    fixtures._send(client, cid, "帮我看看订单")
    first = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert first.status_code == 200, first.text
    count = len(provider.calls)
    again = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert again.status_code == 200
    assert len(provider.calls) == count
    assert again.json()["observationId"] == first.json()["observationId"]

    styled = client.post(f"/api/support/reception/{cid}/assistant?style=concise", headers=SUPPORT)
    assert styled.status_code == 200, styled.text
    assert len(provider.calls) > count

    count = len(provider.calls)
    fixtures._send(client, cid, "还有一个问题", key="later")
    changed = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert changed.status_code == 200
    assert len(provider.calls) > count
