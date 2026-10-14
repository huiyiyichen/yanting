"""队列等待时长（P1-1 队列项），经 HTTP 验收。先列失败方式：
W1 队列等待口径与 response_wait 规则不一致（应从最后一次可见服务回复之后的第一条消费者消息算起）。
W2 服务方已回复后仍显示等待。
W3 消费者平稳收尾（谢谢/好的）仍显示等待。
W4 队列项不带阈值，前端无法与规则一致判断超时。
"""

from tests.integration import test_reception_workspace as fixtures

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT


def item(client, cid):
    queue = client.get("/api/support/reception/queue", headers=SUPPORT).json()
    return next(i for i in queue["items"] if i["conversationId"] == cid)


def test_waiting_since_follows_rule(workspace):
    client, _, _ = workspace
    cid = fixtures._create(client)
    first = fixtures._send(client, cid, "我的快递怎么还没到", key="c1")
    fixtures._send(client, cid, "到底什么时候到", key="c2")
    row = item(client, cid)
    assert row["waitingSince"] == first["message"]["createdAt"]  # W1
    assert row["waitThresholdSeconds"] == 120  # W4
    client.post(f"/api/support/reception/{cid}/service-mode", headers=SUPPORT, json={"mode": "operator_assisted"})
    client.post(f"/api/support/reception/{cid}/messages", headers=SUPPORT,
                json={"body": "我来帮您查", "clientMessageKey": "op-1"})
    assert item(client, cid)["waitingSince"] is None  # W2
    fixtures._send(client, cid, "好的谢谢", key="c3")
    assert item(client, cid)["waitingSince"] is None  # W3
