"""追踪记录器在并行分支下的父子关系与序号（多 Agent 阶段 3 前置）。

失败方式：
S1 并行分支互相把对方当成父跨度（旧实现用 Trace 实例上的共享栈）；
S2 分支内的模型调用挂到别的分支下面；
S3 多线程同时开跨度时 seq 重复或与列表顺序不一致。
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from app.audit import tracer


def test_parallel_branches_share_the_fork_point_as_parent():
    trace = tracer.start_trace("reception", "customer_message", conversation_id="c1")
    barrier = threading.Barrier(3)

    def branch(name: str):
        with trace.span(name, "query") as span:
            barrier.wait(timeout=5)  # 三个分支同时处于打开状态
            child = trace.model_call(stage=f"{name}-call", started=time.perf_counter(), messages=None)
            time.sleep(0.01)
        return span.span_id, child.parent_span_id

    with trace.span("fork", "decision") as fork:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(copy_context().run, branch, n) for n in ("trajectory", "knowledge", "vision")]
            results = [f.result() for f in futures]

    by_id = {s.span_id: s for s in trace.spans}
    for span_id, call_parent in results:
        assert by_id[span_id].parent_span_id == fork.span_id  # S1
        assert call_parent == span_id  # S2
    seqs = [s.seq for s in trace.spans]
    assert seqs == list(range(len(trace.spans)))  # S3


def test_sequential_nesting_still_works():
    trace = tracer.start_trace("reception", "customer_message", conversation_id="c2")
    with trace.span("outer") as outer:
        with trace.span("inner") as inner:
            pass
        with trace.span("sibling") as sibling:
            pass
    after = trace.decision("after", [])
    assert inner.parent_span_id == outer.span_id
    assert sibling.parent_span_id == outer.span_id
    assert after.parent_span_id is None
