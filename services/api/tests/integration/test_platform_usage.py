"""用量与成本统计接口（P1-7）。失败方式：
G1 Mock 调用计入成本统计（应分开，live 统计只算非 Mock）。
G2 按节点汇总缺少起草/核验区分。
G3 每条回复平均成本的分母不是成功产出的回复运行数。
G4 时间范围参数不生效。
"""

from tests.integration import test_reception_workspace as fixtures

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT


def test_usage_summary_separates_mock_and_groups_by_stage(workspace):
    client, _, _ = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "在吗")
    assert client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT).status_code == 200
    view = client.get("/api/platform/usage", headers=SUPPORT).json()
    assert view["mock"]["calls"] >= 2
    assert view["live"]["calls"] == 0 and view["live"]["estimatedCost"] is None
    stages = {row["stage"] for row in view["mock"]["byStage"]}
    assert {"draft", "verify"} <= stages
    assert view["mock"]["replyRuns"] == 1
    assert view["mock"]["callsPerReply"] == view["mock"]["calls"]
    future = client.get("/api/platform/usage?from=2099-01-01", headers=SUPPORT).json()
    assert future["mock"]["calls"] == 0


def test_usage_groups_model_calls_by_agent_with_trace_link(workspace):
    """G5 成本没有按 Agent 分组，或分组行无法跳到对应追踪（阶段 5）。"""
    client, _, _ = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "在吗")
    assert client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT).status_code == 200
    view = client.get("/api/platform/usage", headers=SUPPORT).json()
    agents = {row["agent"]: row for row in view["mock"]["byAgent"]}
    assert {"composer", "verifier"} <= set(agents)
    assert sum(row["calls"] for row in agents.values()) == view["mock"]["calls"]
    trace_id = agents["composer"]["latestTraceId"]
    assert trace_id and client.get(f"/api/platform/traces/{trace_id}", headers=SUPPORT).status_code == 200
    assert view["live"]["byAgent"] == []
