"""按 Agent 分配模型（反馈 10-18 #4）。

失败方式：
A1 配置页拿不到 LLM 型 Agent 列表与默认模型；
A2 可以保存网关没有的模型名（会把接待切到不存在的模型）或未知 Agent；
A3 保存后编排仍用默认模型调用该 Agent；追踪 span 没记录实际请求/返回的模型；
A4 未分配的 Agent 被误改，清空分配后不回退默认模型。
"""
from tests.integration import test_reception_workspace as fixtures
from tests.integration.test_trace_foundation import _generate

workspace = fixtures.workspace
SUPPORT = fixtures.SUPPORT


def _calls(client, view, name):
    detail = client.get(f"/api/platform/traces/{view['modelUsage']['traceId']}", headers=SUPPORT).json()
    parents = {s["spanId"]: s["name"] for s in detail["spans"]}
    return [s for s in detail["spans"] if s["kind"] == "model_call" and parents.get(s["parentSpanId"]) == name]


def test_agent_model_assignment_is_saved_and_used(workspace):
    client, _factory, _ = workspace
    provider = client.app.state.runtime.model_provider
    default = provider.model_id
    provider.list_models = lambda: [default, "qwen-max-latest"]

    listed = client.get("/api/platform/agent-models", headers=SUPPORT).json()["agents"]
    keys = [a["key"] for a in listed]
    assert {"composer", "verifier", "vision", "handoff_summary", "memory"} <= set(keys)
    assert all(a["model"] is None for a in listed)
    assert next(a for a in listed if a["key"] == "composer")["defaultModel"] == default

    bad = client.put("/api/platform/agent-models", headers=SUPPORT, json={"assignments": {"composer": "nope-model"}})
    assert bad.status_code in (400, 422)
    bad = client.put("/api/platform/agent-models", headers=SUPPORT, json={"assignments": {"router": default}})
    assert bad.status_code in (400, 422)

    saved = client.put("/api/platform/agent-models", headers=SUPPORT,
                       json={"assignments": {"composer": "qwen-max-latest"}}).json()["agents"]
    assert next(a for a in saved if a["key"] == "composer")["model"] == "qwen-max-latest"
    assert next(a for a in saved if a["key"] == "verifier")["model"] is None

    _cid, view = _generate(client)
    calls = _calls(client, view, "composer")
    assert calls and all(c["modelRequested"] == "qwen-max-latest" for c in calls)
    assert calls[-1]["modelReturned"] == "qwen-max-latest"

    client.put("/api/platform/agent-models", headers=SUPPORT, json={"assignments": {"composer": None}})
    _cid, view = _generate(client)
    assert all(c["modelRequested"] == default for c in _calls(client, view, "composer"))
