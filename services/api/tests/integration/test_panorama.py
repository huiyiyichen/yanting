"""AI 接待全景接口（全景方案 3.6 / 3.9），Mock 模型，不声称 live 质量。

先列失败方式：
F1 泳道与会话模式不一致：已人工回复仍在“待人工”；AI 模式不在“AI 接待中”。
F4 等待计时在服务回复后不停止，或把系统“已转人工”提示当作回复。
F5 官方历史会话混入全景。
F7 任务结束后步骤登记未清理，进度停在中间；上一轮耗时丢失。
F8 转人工原因不按方案取值（客户要求人工 / 就医 · 安全转人工 / 投诉风险 …），或缺少触发原话。
F9 活动窗口外的会话仍出现在全景。
F10 进程重启（内存登记表清空）后上一轮记录丢失；上一轮没有可跳转的追踪号（多 Agent T8）。
F11 上一轮仍按固定步骤显示，而非追踪里实际运行的 Agent（多 Agent 8.2）；并行组没有标记；
    重试的同一 Agent 显示成两行；子跨度（模型调用）混进列表。
"""

from tests.integration import test_reception_workspace as fixtures
from tests.integration.test_auto_reception import jobs

from app.domain.consumer_service import job_progress
from app.domain.consumer_service.auto_reception import process_job

workspace = fixtures.workspace
SUPPORT, CUSTOMER = fixtures.SUPPORT, fixtures.CUSTOMER


def view(client):
    response = client.get("/api/support/reception/panorama", headers=SUPPORT)
    assert response.status_code == 200, response.text
    return {item["conversationId"]: item for item in response.json()["items"]}, response.json()


def test_lanes_follow_service_mode(workspace):
    client, factory, _ = workspace
    job_progress.reset()
    ai = fixtures._create(client)
    fixtures._send(client, ai, "包裹到哪了")
    items, body = view(client)
    assert items[ai]["lane"] == "ai" and items[ai]["aiJob"] == "queued" and body["queued"] >= 1
    assert items[ai]["waitingSince"] and items[ai]["emotionBands"]
    process_job(client.app.state.runtime, jobs(factory, ai)[0].job_id)
    items, _ = view(client)
    assert items[ai]["aiJob"] is None and items[ai]["waitingSince"] is None  # F4 AI 回复后停止计时
    run = items[ai]["lastRun"]
    assert run and run["outcome"] == "sent" and [s["name"] for s in run["steps"]][-1] == "发送闸门"
    assert all(s["status"] == "done" for s in run["steps"])  # F7
    assert job_progress.running_for(ai) is None

    wait = fixtures._create(client)
    fixtures._send(client, wait, "你好")
    client.post(f"/api/customer/conversations/{wait}/handoff", headers=CUSTOMER)
    items, _ = view(client)
    assert items[wait]["lane"] == "wait"
    assert items[wait]["handoffReason"] == "客户要求人工" and items[wait]["handoffQuote"] == "你好"
    assert items[wait]["waitingSince"]  # F4 系统转人工提示不算回复
    client.post(f"/api/support/reception/{wait}/messages", headers=SUPPORT,
                json={"body": "我来跟进", "clientMessageKey": "op-1"})
    items, _ = view(client)
    assert items[wait]["lane"] == "human" and items[wait]["handler"] and items[wait]["waitingSince"] is None


def test_safety_handoff_reason_and_official_excluded(workspace):
    client, factory, _ = workspace
    job_progress.reset()
    cid = fixtures._create(client)
    fixtures._send(client, cid, "用了你们面膜脸过敏，我人现在在医院，已经就医了！")
    process_job(client.app.state.runtime, jobs(factory, cid)[0].job_id)
    items, _ = view(client)
    assert items[cid]["lane"] == "wait"
    assert items[cid]["handoffReason"] == "就医 · 安全转人工"
    steps = {s["name"]: s["status"] for s in items[cid]["lastRun"]["steps"]}
    assert steps["安全闸门"] == "fail" and "共情起草" not in steps
    assert all(not key.startswith("S0") for key in items)  # F5 官方会话 S00xxx 不进入


def test_active_window(workspace, monkeypatch):
    client, _, _ = workspace
    cid = fixtures._create(client)
    fixtures._send(client, cid, "包裹到哪了")
    from datetime import UTC, datetime, timedelta

    from app.domain.consumer_service import panorama as module

    with client.app.state.runtime.new_session() as session:
        later = module.panorama(session, window_minutes=120, now=datetime.now(UTC) + timedelta(hours=3))
        unlimited = module.panorama(session, window_minutes=0, now=datetime.now(UTC) + timedelta(hours=3))
    assert cid not in {i.conversation_id for i in later.items}
    assert cid in {i.conversation_id for i in unlimited.items}


def test_last_run_survives_restart_from_trace(workspace):
    client, factory, _ = workspace
    ai = fixtures._create(client)
    fixtures._send(client, ai, "包裹到哪了")
    process_job(client.app.state.runtime, jobs(factory, ai)[0].job_id)
    job_progress.reset()
    items, _ = view(client)
    run = items[ai]["lastRun"]
    assert run and run["outcome"] == "sent" and run["traceId"].startswith("trc-")
    names = [s["name"] for s in run["steps"]]
    assert "共情起草" in names and "发送闸门" in names and names.index("共情起草") < names.index("发送闸门")
    assert all(s["status"] in {"done", "skipped"} for s in run["steps"])


def test_last_run_lists_agents_with_parallel_groups(workspace):
    from datetime import UTC, datetime

    from app.audit.trace_models import AgentSpanRow, AgentTraceRow
    from app.domain.consumer_service.panorama import _last_run_from_trace

    _, factory, _ = workspace
    t0 = datetime(2026, 5, 1, tzinfo=UTC)
    rows = [("s1", None, 0, "decision", "safety_gate", None, "ok", 5, 1), ("s2", None, 1, "agent", "trajectory", "fanout", "ok", 300, 1),
            ("s3", None, 2, "agent", "knowledge", "fanout", "ok", 800, 1), ("s4", "s3", 3, "model", "knowledge", None, "ok", 700, 1),
            ("s5", None, 4, "agent", "vision", "fanout", "skipped", 0, 1), ("s6", None, 5, "agent", "composer", None, "failed", 900, 1),
            ("s7", None, 6, "agent", "composer", None, "ok", 1100, 2), ("s8", None, 7, "decision", "send_gate", None, "ok", 3, 1)]
    with factory() as session:
        session.add(AgentTraceRow(trace_id="trc-x", graph="reception", trigger_type="message", conversation_id="C-X", status="sent", started_at=t0))
        for sid, parent, seq, kind, name, group, status, ms, attempt in rows:
            session.add(AgentSpanRow(span_id=sid, trace_id="trc-x", parent_span_id=parent, seq=seq, kind=kind, name=name,
                                     parallel_group=group, status=status, duration_ms=ms, attempt=attempt, started_at=t0))
        session.commit()
        run = _last_run_from_trace(session, "C-X")
    assert [(s["name"], s.get("group"), s["status"], s["durationMs"]) for s in run["steps"]] == [
        ("安全闸门", None, "done", 5), ("轨迹查询", "fanout", "done", 300), ("知识", "fanout", "done", 800),
        ("视觉", "fanout", "skipped", 0), ("共情起草", None, "done", 2000), ("发送闸门", None, "done", 3)]
    assert run["steps"][4]["attempts"] == 2
