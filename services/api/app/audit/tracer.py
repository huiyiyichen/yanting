"""Agent 追踪记录器（多 Agent 设计 7.3）。

一次触发对应一个追踪；运行期间跨度先记在内存里，在业务提交点用 ``flush`` 写入同一个
会话（失败路径在 ``record_failure`` 等处写入）。记录器出错只写日志和计数，绝不让接待失败。
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.logging_setup import get_logger

_log = get_logger(__name__)
_current: contextvars.ContextVar[Trace | None] = contextvars.ContextVar("yt_trace", default=None)
#: 记录器自身失败次数（进程内），供完整性检查与健康页读取
recorder_errors = 0


def _now() -> datetime:
    return datetime.now(UTC)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Span:
    span_id: str
    name: str
    kind: str
    label: str = ""
    parent_span_id: str | None = None
    attempt: int = 1
    parallel_group: str | None = None
    status: str = "running"
    started_at: datetime = field(default_factory=_now)
    ended_at: datetime | None = None
    duration_ms: int | None = None
    reasons: list[Any] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    seq: int = 0
    _t0: float = field(default_factory=time.perf_counter)

    def end(self, status: str = "ok") -> None:
        if self.ended_at is None:
            self.status = status
            self.ended_at = _now()
            self.duration_ms = round((time.perf_counter() - self._t0) * 1000)


@dataclass
class Trace:
    trace_id: str
    graph: str
    trigger_type: str
    conversation_id: str | None = None
    trigger_message_id: str | None = None
    job_id: str | None = None
    orchestration: str = "single"
    mode: str | None = None
    mode_revision: int | None = None
    message_revision: int | None = None
    versions: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    outcome_message_id: str | None = None
    started_at: datetime = field(default_factory=_now)
    ended_at: datetime | None = None
    spans: list[Span] = field(default_factory=list)
    artifacts: dict[str, tuple[str, str]] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    _stack: list[str] = field(default_factory=list)
    _flushed_artifacts: set[str] = field(default_factory=set)
    _flushed_citations: int = 0

    # ── 记录 ─────────────────────────────────────────────────────────────
    def _new_span(self, name: str, kind: str, **values: Any) -> Span:
        parent = values.pop("parent_span_id", None) or (self._stack[-1] if self._stack else None)
        span = Span(span_id=f"spn-{uuid.uuid4().hex[:16]}", name=name, kind=kind,
                    parent_span_id=parent, seq=len(self.spans), **values)
        self.spans.append(span)
        return span

    @contextlib.contextmanager
    def span(self, name: str, kind: str = "agent", **values: Any) -> Iterator[Span]:
        span = self._new_span(name, kind, **values)
        self._stack.append(span.span_id)
        try:
            yield span
        except Exception as exc:
            span.extra.setdefault("error_code", str(getattr(exc, "code", type(exc).__name__))[:100])
            span.extra.setdefault("error_detail", str(getattr(exc, "detail", None) or exc)[:500])
            span.end("timeout" if "Timeout" in type(exc).__name__ else "failed")
            raise
        finally:
            if self._stack and self._stack[-1] == span.span_id:
                self._stack.pop()
            span.end(span.status if span.status != "running" else "ok")

    def decision(self, name: str, reasons: list[Any], *, status: str = "ok", label: str = "") -> Span:
        span = self._new_span(name, "decision", label=label, reasons=list(reasons))
        span.end(status)
        return span

    def skipped(self, name: str, reason: str, *, kind: str = "agent", label: str = "") -> Span:
        span = self._new_span(name, kind, label=label, reasons=[reason])
        span.end("skipped")
        return span

    def artifact(self, kind: str, content: Any) -> str:
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
        digest = _sha(text)
        self.artifacts.setdefault(digest, (kind, text))
        return digest

    def model_call(self, *, stage: str, started: float, messages: list[Any] | None, result: Any = None,
                   error: Exception | None = None, model_requested: str | None = None,
                   tier: str | None = None, prompt_code: str | None = None,
                   prompt_revision: str | None = None, contract_version: str | None = None) -> Span | None:
        """Every model call is a span, including failed, timed-out and cancelled ones (T2/T3)."""
        global recorder_errors
        try:
            return self._model_call(stage, started, messages, result, error, model_requested, tier,
                                    prompt_code, prompt_revision, contract_version)
        except Exception:  # recording never breaks the call it records
            recorder_errors += 1
            _log.exception("trace model_call failed trace_id=%s", self.trace_id)
            return None

    def _model_call(self, stage, started, messages, result, error, model_requested, tier,
                    prompt_code, prompt_revision, contract_version) -> Span:
        span = self._new_span(stage, "model_call", label=stage)
        span.extra["tier"] = tier
        span._t0 = started
        payload = [{"role": m.role, "content": m.content,
                    "images": len(getattr(m, "image_data_urls", []) or [])} for m in (messages or [])]
        if payload:
            system = payload[0]["content"] if payload[0]["role"] == "system" else ""
            span.extra["prompt_sha256"] = _sha(system) if system else None
            if system:
                self.artifact("rendered_prompt", system)
            span.extra["input_artifact"] = self.artifact("input_payload", payload)
        span.extra.update(model_requested=model_requested, prompt_code=prompt_code,
                          prompt_revision=prompt_revision, contract_version=contract_version)
        if result is not None:
            span.extra.update(
                model_returned=getattr(result, "model", None), is_mock=getattr(result, "is_mock", None),
                prompt_tokens=getattr(result, "prompt_tokens", None),
                completion_tokens=getattr(result, "completion_tokens", None),
                cached_tokens=getattr(result, "cached_tokens", None),
                finish_reason=getattr(result, "finish_reason", None),
                output_artifact=self.artifact("model_output", getattr(result, "text", "") or ""),
            )
        if error is not None:
            span.extra.update(error_code=str(getattr(error, "code", type(error).__name__))[:100],
                              error_detail=str(getattr(error, "detail", None) or error)[:500])
            name = type(error).__name__
            span.end("timeout" if "Timeout" in name else "cancelled" if "Conflict" in name else "failed")
        else:
            span.end("ok")
        return span

    def cite(self, *, message_id: str | None, style: str, segment_index: int, text: str,
             source_id: str, source_record_id: str | None, verdict: str) -> None:
        self.citations.append({
            "message_id": message_id, "reply_style": style, "segment_index": segment_index,
            "segment_text": text, "source_id": source_id, "source_record_id": source_record_id,
            "verdict": verdict,
        })

    def finish(self, status: str, *, outcome_message_id: str | None = None) -> None:
        self.status = status
        self.outcome_message_id = outcome_message_id or self.outcome_message_id
        self.ended_at = self.ended_at or _now()
        for span in self.spans:
            if span.ended_at is None:
                span.end("cancelled")

    def totals(self) -> dict[str, Any]:
        calls = [s for s in self.spans if s.kind == "model_call"]

        def total(key: str) -> int | None:
            values = [s.extra.get(key) for s in calls if s.extra.get(key) is not None]
            return sum(values) if values else None

        end = self.ended_at or _now()
        return {
            "calls": len(calls), "failedCalls": sum(s.status != "ok" for s in calls),
            "promptTokens": total("prompt_tokens"), "completionTokens": total("completion_tokens"),
            "cachedTokens": total("cached_tokens"),
            "durationMs": round((end - self.started_at).total_seconds() * 1000),
        }

    # ── 写入 ─────────────────────────────────────────────────────────────
    def flush(self, session: Any) -> bool:
        """Write everything recorded so far into ``session``; never raises."""
        global recorder_errors
        from app.audit.trace_models import (
            AgentArtifactRow,
            AgentSpanRow,
            AgentTraceRow,
            ReplyCitationRow,
        )

        try:
            with session.begin_nested():
                row = session.get(AgentTraceRow, self.trace_id) or AgentTraceRow(trace_id=self.trace_id)
                row.graph, row.trigger_type = self.graph, self.trigger_type
                row.conversation_id, row.trigger_message_id = self.conversation_id, self.trigger_message_id
                row.job_id, row.orchestration = self.job_id, self.orchestration
                row.mode, row.mode_revision, row.message_revision = (
                    self.mode, self.mode_revision, self.message_revision)
                row.versions_json = json.dumps(self.versions, ensure_ascii=False, default=str)
                row.status, row.outcome_message_id = self.status, self.outcome_message_id
                row.started_at, row.ended_at = self.started_at, self.ended_at
                row.totals_json = json.dumps(self.totals())
                session.add(row)
                for span in self.spans:
                    stored = session.get(AgentSpanRow, span.span_id) or AgentSpanRow(span_id=span.span_id)
                    stored.trace_id, stored.parent_span_id, stored.seq = (
                        self.trace_id, span.parent_span_id, span.seq)
                    stored.kind, stored.name, stored.label = span.kind, span.name, span.label
                    stored.attempt, stored.parallel_group, stored.status = (
                        span.attempt, span.parallel_group, span.status)
                    stored.started_at, stored.ended_at, stored.duration_ms = (
                        span.started_at, span.ended_at, span.duration_ms)
                    stored.reasons_json = json.dumps(span.reasons, ensure_ascii=False, default=str)
                    for key in ("tier", "model_requested", "model_returned", "is_mock", "prompt_code",
                                "prompt_revision", "prompt_sha256", "contract_version", "prompt_tokens",
                                "completion_tokens", "cached_tokens", "finish_reason", "input_artifact",
                                "output_artifact", "error_code", "error_detail"):
                        value = span.extra.get(key, getattr(span, key, None))
                        if value is not None:
                            setattr(stored, key, value)
                    session.add(stored)
                for digest, (kind, text) in self.artifacts.items():
                    if digest in self._flushed_artifacts or session.get(AgentArtifactRow, digest):
                        self._flushed_artifacts.add(digest)
                        continue
                    session.add(AgentArtifactRow(sha256=digest, kind=kind, content=text,
                                                 bytes=len(text.encode("utf-8"))))
                    self._flushed_artifacts.add(digest)
                for item in self.citations[self._flushed_citations:]:
                    session.add(ReplyCitationRow(citation_id=f"cit-{uuid.uuid4().hex[:16]}",
                                                 trace_id=self.trace_id, **item))
                self._flushed_citations = len(self.citations)
                session.flush()
            return True
        except Exception:  # pragma: no cover - defensive; business must continue
            recorder_errors += 1
            _log.exception("trace flush failed trace_id=%s", self.trace_id)
            return False


def start_trace(graph: str, trigger_type: str, **values: Any) -> Trace:
    trace = Trace(trace_id=f"trc-{uuid.uuid4().hex[:16]}", graph=graph, trigger_type=trigger_type, **values)
    _current.set(trace)
    return trace


def current() -> Trace | None:
    return _current.get()


@contextlib.contextmanager
def use(trace: Trace | None) -> Iterator[Trace | None]:
    token = _current.set(trace)
    try:
        yield trace
    finally:
        _current.reset(token)
