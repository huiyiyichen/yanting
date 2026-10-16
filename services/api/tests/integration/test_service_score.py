"""服务乐谱接口（全景方案 4.9 / 4.12），官方数据经 HTTP 验收。

先列失败方式：
F2 音符数量或顺序与消息列表不一致。
F8 客服/系统消息带情绪或信号；消费者消息缺情绪。
F9 触发风险的消息没有信号；信号挂到了别的消息上。
F10 等待从每条消费者消息各算一次（应从未回复的首条算到下一条服务回复）；系统消息被当作回复。
F11 读取乐谱写库或调用模型。
"""

from tests.integration import test_reception_workspace as fixtures

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT


def test_score_matches_messages_and_signals(workspace):
    client, _, provider = workspace
    client.post("/api/support/desk/risks/scan", headers=SUPPORT)
    before = len(provider.calls)
    rows = client.get("/api/support/desk/risks", headers=SUPPORT).json()
    cid = next(row["primaryConversationId"] for row in rows if row["primaryConversationId"])
    messages = client.get(f"/api/support/reception/{cid}/messages", headers=SUPPORT).json()
    score = client.get(f"/api/support/desk/conversations/{cid}/score", headers=SUPPORT)
    assert score.status_code == 200, score.text
    notes = score.json()["notes"]
    assert [n["messageId"] for n in notes] == [m["messageId"] for m in messages]
    for note in notes:
        if note["role"] == "customer":
            assert note["level"] in {"calm", "dissatisfied", "angry"} or not note["body"]
        else:
            assert note["level"] is None and note["signals"] == [] and note["highlights"] == []
    detail = client.get(f"/api/support/desk/risks/{next(r['incidentId'] for r in rows if r['primaryConversationId'] == cid)}",
                        headers=SUPPORT).json()
    message_refs = {e["ref"] for e in detail["evidence"] if e["kind"] == "message" and e.get("label") == cid}
    flagged = {n["messageId"] for n in notes if n["signals"]}
    assert flagged <= {m["messageId"] for m in messages}
    if message_refs & {m["messageId"] for m in messages}:
        assert flagged
    for wait in score.json()["waits"]:
        origin = next(n for n in notes if n["messageId"] == wait["fromMessageId"])
        target = next(n for n in notes if n["messageId"] == wait["toMessageId"])
        assert origin["role"] == "customer" and target["role"] in {"operator", "assistant"} and wait["ms"] >= 0
    assert len(provider.calls) == before


def test_wait_starts_at_first_unanswered_customer_message(workspace):
    client, _, _ = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "在吗", key="a")
    fixtures._send(client, cid, "怎么没人回", key="b")
    client.post(f"/api/customer/conversations/{cid}/handoff", headers=fixtures.CUSTOMER)
    client.post(f"/api/support/reception/{cid}/messages", headers=SUPPORT, json={"body": "在的", "clientMessageKey": "op"})
    score = client.get(f"/api/support/desk/conversations/{cid}/score", headers=SUPPORT).json()
    customer = [n for n in score["notes"] if n["role"] == "customer"]
    assert len(score["waits"]) == 1
    assert score["waits"][0]["fromMessageId"] == customer[0]["messageId"]
    reply = next(n for n in score["notes"] if n["role"] == "operator")
    assert score["waits"][0]["toMessageId"] == reply["messageId"]
