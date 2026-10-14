"""画像卡端到端：官方数据 + 本地会话，经 HTTP 读取（P10、P11、P13、P14 与剧情 A/B）。"""

from __future__ import annotations

from tests.integration import test_reception_workspace as fixtures

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def test_story_a_shows_pending_workday_promise_and_time_causal_contacts(workspace):
    client, _, provider = workspace
    calls_before = len(provider.calls)
    response = client.get("/api/support/reception/S00059/profile", headers=SUPPORT)
    assert response.status_code == 200, response.text
    profile = response.json()
    assert profile["alias"] == "魏h**"
    assert profile["aggregation"] == "buyer_alias"
    # S00099 发生在 05/08，晚于 S00059，不得计入（P10）
    assert profile["contacts"]["total"] == 2
    assert profile["lastContact"]["conversationId"] == "S00005"
    promise = next(p for p in profile["promises"] if "3个工作日" in p["text"])
    assert promise["dueAt"].startswith("2026-05-08T15:59:59")  # 05/08 23:59:59 UTC+8
    assert promise["status"] == "pending"
    assert promise["sourceRef"].startswith("message:S00005:")
    assert {item["orderId"] for item in profile["purchases"]} >= {"6920223542160114724"}
    assert "6920294005666782721" not in {item["orderId"] for item in profile["purchases"]}
    assert profile["currentEmotion"] in {"dissatisfied", "angry"}
    assert all(point["level"] is None for point in profile["emotionTrail"] if point["role"] != "customer")
    assert len(provider.calls) == calls_before  # P14 读取不调模型


def test_local_self_description_rejection_and_customer_view_isolation(workspace):
    client, _, _ = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "我是混干皮，不想再叠面霜了")
    profile = client.get(f"/api/support/reception/{cid}/profile", headers=SUPPORT).json()
    assert profile["skin"]["text"] == "混干皮"
    assert profile["memory"]["rejected"][0]["sourceRef"].startswith(f"message:{cid}:")
    assert "叠面霜" in profile["memory"]["rejected"][0]["text"]
    # 客户视角不得读取画像
    assert client.get(f"/api/support/reception/{cid}/profile", headers=CUSTOMER).status_code in {401, 403}
