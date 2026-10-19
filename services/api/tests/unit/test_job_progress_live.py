"""全景“AI 处理中”读实时跨度（阶段 5）。

失败方式：
L1 有追踪时仍显示固定六步，看不到分诊、并行 Worker。
L2 运行中的节点没有已用时间，或状态不是 active。
L3 修复轮的起草没合并成一行带次数。
L4 运行中给出 traceId（追踪还没落库，链接打不开）。
"""

import time

from app.audit import tracer
from app.domain.consumer_service import job_progress


def test_running_trace_shows_actual_agents():
    job_progress.reset()
    trace = tracer.start_trace("reception", "customer_message", conversation_id="c1", job_id="j1",
                               orchestration="multi")
    job_progress.begin("j1", "c1", trace)
    with trace.span("triage", "agent"):
        pass
    trace.skipped("knowledge", "分诊未派发知识", kind="query")
    with trace.span("trajectory", "query", parallel_group="evidence"):
        pass
    for attempt in (1, 2):
        with trace.span("composer", "agent", attempt=attempt):
            pass
    with trace.span("verifier", "agent"):
        time.sleep(0.01)
        run = job_progress.running_for("c1")
    steps = {s["name"]: s for s in run["steps"]}
    assert list(steps) == ["分诊", "知识", "轨迹查询", "共情起草", "核验"]  # L1
    assert steps["知识"]["status"] == "skipped" and steps["轨迹查询"]["group"] == "evidence"
    assert steps["核验"]["status"] == "active" and steps["核验"]["durationMs"] >= 10  # L2
    assert steps["共情起草"]["attempts"] == 2  # L3
    assert "traceId" not in run  # L4
    job_progress.reset()


def test_without_trace_falls_back_to_fixed_steps():
    job_progress.reset()
    job_progress.begin("j2", "c2")
    run = job_progress.running_for("c2")
    assert [s["name"] for s in run["steps"]] == list(job_progress.DISPLAY_STEPS)
    job_progress.reset()
