"""自动接待任务的运行中步骤登记（全景方案 3.6）。

进程内登记表：任务 ID → 当前步骤与已用时间；任务结束即移除，并把本轮各步骤耗时
记为该会话的“上一轮 AI 处理”。不落库：进程重启后上一轮记录清空，属预期。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

DISPLAY_STEPS = ("安全检查", "读取轨迹", "知识检索", "起草", "核验", "发送")
#: 工作流节点名 → 显示步骤；图片读取并入读取轨迹，两个核验节点合并
NODE_TO_STEP = {
    "服务轨迹": "读取轨迹", "图片读取": "读取轨迹", "知识检索": "知识检索", "理解与起草": "起草",
    "来源与字段校验": "核验", "独立事实核验": "核验", "输出确认": "核验",
}


@dataclass
class StepState:
    name: str
    status: str = "pending"  # pending / active / done / fail
    duration_ms: int = 0
    started: float | None = None


@dataclass
class RunState:
    job_id: str
    conversation_id: str
    steps: dict[str, StepState] = field(default_factory=lambda: {n: StepState(n) for n in DISPLAY_STEPS})
    outcome: str | None = None
    #: 本轮的追踪（进程内对象）。有它时全景按实际运行的 Agent 跨度显示，而不是固定步骤
    trace: Any = None

    def snapshot(self, now: float | None = None) -> list[dict]:
        now = time.perf_counter() if now is None else now
        out = []
        for step in self.steps.values():
            elapsed = step.duration_ms + (round((now - step.started) * 1000) if step.started is not None else 0)
            out.append({"name": step.name, "status": step.status, "durationMs": elapsed})
        return out


_lock = Lock()
_running: dict[str, RunState] = {}
_last: dict[str, dict] = {}


def begin(job_id: str, conversation_id: str, trace: Any = None) -> None:
    with _lock:
        _running[job_id] = RunState(job_id, conversation_id, trace=trace)


#: 跨度名 → 全景显示名（与 panorama.AGENT_LABEL 一致）
SPAN_LABEL = {
    "safety_gate": "安全闸门", "triage": "分诊", "trajectory": "轨迹查询", "knowledge": "知识", "vision": "视觉",
    "composer": "共情起草", "program_check": "程序核验", "verifier": "核验", "output_gate": "输出闸门",
    "send_gate": "发送闸门", "rewriter": "改写",
}


def live_steps(trace: Any, now: float | None = None) -> list[dict] | None:
    """从运行中的追踪读实时跨度：每个顶层 Agent 一行，运行中的显示已用时间，多次尝试合并。"""
    spans = list(getattr(trace, "spans", None) or [])
    if not spans:
        return None
    now = time.perf_counter() if now is None else now
    steps: dict[str, dict] = {}
    for span in sorted(spans, key=lambda item: item.seq):
        if span.parent_span_id or span.kind in {"model", "model_call"}:
            continue
        if span.ended_at is None:
            status, elapsed = "active", round((now - span._t0) * 1000)
        else:
            failed = span.status not in {"ok", "skipped"}
            status = "fail" if failed else "skipped" if span.status == "skipped" else "done"
            elapsed = span.duration_ms or 0
        step = steps.get(span.name)
        if step is None:
            steps[span.name] = {"name": SPAN_LABEL.get(span.name) or span.label or span.name, "status": status,
                                "durationMs": elapsed, "group": span.parallel_group, "attempts": 1}
            continue
        step["durationMs"] += elapsed
        step["attempts"] += 1
        step["status"] = status
    return list(steps.values()) or None


def mark(job_id: str, step: str, status: str) -> None:
    """status: running / passed / needs_repair / failed / handoff。"""
    name = NODE_TO_STEP.get(step, step)
    if name not in DISPLAY_STEPS:
        return
    now = time.perf_counter()
    with _lock:
        run = _running.get(job_id)
        if run is None:
            return
        state = run.steps[name]
        if status == "running":
            if state.started is None:
                state.started = now
            state.status = "active"
            return
        if state.started is not None:
            state.duration_ms += round((now - state.started) * 1000)
            state.started = None
        state.status = "fail" if status in {"failed", "handoff"} else "done"


def end(job_id: str, outcome: str) -> None:
    with _lock:
        run = _running.pop(job_id, None)
        if run is None:
            return
        run.outcome = outcome
        for state in run.steps.values():
            if state.started is not None:
                state.duration_ms += round((time.perf_counter() - state.started) * 1000)
                state.started = None
                state.status = "fail" if outcome != "sent" else "done"
        _last[run.conversation_id] = {"jobId": job_id, "outcome": outcome, "steps": run.snapshot()}


def running_for(conversation_id: str) -> dict | None:
    with _lock:
        for run in _running.values():
            if run.conversation_id == conversation_id:
                steps = live_steps(run.trace) if run.trace is not None else None
                # 追踪要到本轮结束才落库，运行中不给 traceId，免得“查看追踪”打不开
                return {"jobId": run.job_id, "steps": steps or run.snapshot()}
    return None


def last_for(conversation_id: str) -> dict | None:
    with _lock:
        return _last.get(conversation_id)


def reset() -> None:
    with _lock:
        _running.clear()
        _last.clear()
