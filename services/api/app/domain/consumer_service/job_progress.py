"""自动接待任务的运行中步骤登记（全景方案 3.6）。

进程内登记表：任务 ID → 当前步骤与已用时间；任务结束即移除，并把本轮各步骤耗时
记为该会话的“上一轮 AI 处理”。不落库：进程重启后上一轮记录清空，属预期。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

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


def begin(job_id: str, conversation_id: str) -> None:
    with _lock:
        _running[job_id] = RunState(job_id, conversation_id)


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
                return {"jobId": run.job_id, "steps": run.snapshot()}
    return None


def last_for(conversation_id: str) -> dict | None:
    with _lock:
        return _last.get(conversation_id)


def reset() -> None:
    with _lock:
        _running.clear()
        _last.clear()
