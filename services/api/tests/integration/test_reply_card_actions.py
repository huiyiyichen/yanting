"""回复建议交互升级（P1-3），经 HTTP 验收。先列失败方式：
A1 改写用了主模型而不是快速模型档。
A2 改写结果删改事实时仍替换原文（应 422 并保留原文）。
A3 改写在建议过期或未核验时仍可执行。
A4 单风格重生成把其他风格也替换掉了。
A5 流式接口没有按工作流节点推送阶段事件，或完成事件里没有可用建议。
A6 流式接口失败时伪装成功（应推送 error 事件，并记录失败运行）。
A7 编辑后采用不记录编辑距离，采纳率统计漏掉编辑后采用。
A8 客户视角可以调用改写或流式接口。
"""

import json

from tests.integration import test_reception_workspace as fixtures
from tests.integration.test_grounded_workflow import make_provider

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER

TWO_STYLES = {**json.loads(fixtures.OUTPUT), "reply_suggestions": [
    {"style": "recommended", "body": "我来核对这笔订单，方便提供订单号吗？"},
    {"style": "concise", "body": "麻烦提供订单号，我来核对。"},
]}


def setup(client, provider, draft=TWO_STYLES):
    cid = fixtures._create(client)
    fixtures._send(client, cid, "查询订单物流")
    make_provider(provider, lambda _: draft)
    view = client.post(f"/api/support/reception/{cid}/assistant", headers=SUPPORT)
    assert view.status_code == 200, view.text
    return cid, view.json()


def test_rewrite_uses_fast_tier_and_guards_facts(workspace):
    client, _, provider = workspace
    cid, _ = setup(client, provider)
    tiers = []

    def complete(messages, **kwargs):
        tiers.append(kwargs.get("model_tier"))
        from app.integrations.model_provider import ChatResult
        return ChatResult(text=json.dumps({"text": reply}, ensure_ascii=False), model="fast-fixture",
                          latency_seconds=0, is_mock=True)
    provider.complete = complete
    original = "我来核对这笔订单，方便提供订单号吗？"
    reply = "亲亲别着急，我这就帮您核对这笔订单，方便发一下订单号吗？"
    ok = client.post(f"/api/support/reception/{cid}/assistant/rewrite", headers=SUPPORT,
                     json={"style": "recommended", "text": original, "instruction": "gentler"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["text"] == reply and tiers == ["fast"]
    reply = "我来核对这笔订单，预计3天内到账。"
    bad = client.post(f"/api/support/reception/{cid}/assistant/rewrite", headers=SUPPORT,
                      json={"style": "recommended", "text": original, "instruction": "concise"})
    assert bad.status_code == 422 and "新增" in bad.text
    assert client.post(f"/api/support/reception/{cid}/assistant/rewrite", headers=CUSTOMER,
                       json={"style": "recommended", "text": original, "instruction": "gentler"}).status_code in {401, 403}


def test_single_style_regeneration_keeps_other_styles(workspace):
    client, _, provider = workspace
    cid, first = setup(client, provider)
    make_provider(provider, lambda _: {**TWO_STYLES, "reply_suggestions": [
        {"style": "recommended", "body": "新的推荐：方便提供订单号吗？"},
        {"style": "concise", "body": "新的简洁：请发订单号。"},
    ]})
    again = client.post(f"/api/support/reception/{cid}/assistant?style=concise", headers=SUPPORT).json()
    bodies = {item["style"]: item["body"] for item in again["replySuggestions"]}
    assert bodies["concise"] == "新的简洁：请发订单号。"
    assert bodies["recommended"] == next(i["body"] for i in first["replySuggestions"] if i["style"] == "recommended")


def test_stream_pushes_stages_then_done(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "查询订单物流")
    make_provider(provider, lambda _: TWO_STYLES)
    with client.stream("GET", f"/api/support/reception/{cid}/assistant/stream", headers=SUPPORT) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
    stages = [e["name"] for e in events if e["type"] == "stage"]
    assert stages[0] == "服务轨迹" and "理解与起草" in stages
    done = events[-1]
    assert done["type"] == "done" and done["view"]["replySuggestions"]


def test_stream_failure_is_reported_not_faked(workspace):
    client, _, provider = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "查询订单物流")
    make_provider(provider, lambda _: {"not": "a draft"})
    with client.stream("GET", f"/api/support/reception/{cid}/assistant/stream", headers=SUPPORT) as response:
        events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
    assert events[-1]["type"] == "error" and events[-1]["code"]
    assert client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT).json() is None


def test_edited_adoption_records_distance_and_counts(workspace):
    client, _, provider = workspace
    cid, view = setup(client, provider)
    response = client.post(f"/api/support/reception/{cid}/suggestion-action", headers=SUPPORT, json={
        "inputHash": view["inputHash"], "style": "recommended", "action": "adopt_edited",
        "editedText": "我来核对这笔订单，方便发一下订单号吗？",
    })
    assert response.status_code in {200, 204}, response.text
    stats = client.get("/api/support/desk/stats", headers=SUPPORT).json()
    assert stats["suggestionAdoptionRate"] == 1.0
    cached = client.get(f"/api/support/conversations/{cid}/assistant", headers=SUPPORT).json()
    assert cached["adoptedCount"] == 1
