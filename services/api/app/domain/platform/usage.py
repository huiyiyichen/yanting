"""模型用量与成本统计（改进方案 P1-7）。

数据来自审计中的 model_call 事件（每次实际模型调用一条，含节点、型号、Token、缓存命中）。
Mock 与 live 分开统计；价格表按模型 ID 配置（每百万 Token 元），未配置的模型不估算成本。
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.schemas.base import ApiModel

CST = timezone(timedelta(hours=8))


class ModelPrice(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    input: float
    cachedInput: float | None = None
    output: float


def parse_price_table(raw: str) -> dict[str, ModelPrice]:
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return {model: ModelPrice.model_validate(value) for model, value in data.items()}
    except (json.JSONDecodeError, ValidationError, AttributeError) as exc:
        raise ValueError(f"模型价格表格式错误：{exc}") from exc


def estimate_cost(prices: dict[str, ModelPrice], model: str, *, prompt: int | None, cached: int | None,
                  completion: int | None) -> float | None:
    price = prices.get(model)
    if price is None or prompt is None or completion is None:
        return None
    cached = cached or 0
    if cached > prompt:
        return None
    cached_price = price.cachedInput if price.cachedInput is not None else price.input
    return ((prompt - cached) * price.input + cached * cached_price + completion * price.output) / 1_000_000


class StageUsage(ApiModel):
    stage: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    latency_seconds: float


class ModelUsage(ApiModel):
    model: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    estimated_cost: float | None


class AgentUsage(ApiModel):
    """按 Agent 汇总（阶段 5）：模型调用跨度挂在哪个 Agent 下就算谁的。"""
    agent: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    latency_seconds: float
    estimated_cost: float | None
    traces: int
    latest_trace_id: str | None


class UsageBucket(ApiModel):
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cache_hit_rate: float | None
    calls_missing_tokens: int
    estimated_cost: float | None
    reply_runs: int
    calls_per_reply: float | None
    cost_per_reply: float | None
    by_stage: list[StageUsage]
    by_model: list[ModelUsage]
    by_day: dict[str, int]
    by_agent: list[AgentUsage] = Field(default_factory=list)


class UsageView(ApiModel):
    live: UsageBucket
    mock: UsageBucket
    priced_models: list[str]


def _bound(value: date | None, *, end: bool) -> datetime | None:
    if value is None:
        return None
    moment = datetime.combine(value + timedelta(days=1) if end else value, time.min, tzinfo=CST)
    return moment.astimezone(UTC).replace(tzinfo=None)


def usage_summary(session: Session, prices: dict[str, ModelPrice], *, start: date | None = None,
                  end: date | None = None) -> UsageView:
    from app.domain.case_state.models import AuditEventRow
    from app.domain.consumer_service.models import AssistantRunRow

    query = select(AuditEventRow).where(AuditEventRow.event_type == "model_call")
    runs = select(AssistantRunRow).where(AssistantRunRow.status.in_(("verified", "partial", "needs_review")))
    if (lower := _bound(start, end=False)) is not None:
        query = query.where(AuditEventRow.created_at >= lower)
        runs = runs.where(AssistantRunRow.created_at >= lower)
    if (upper := _bound(end, end=True)) is not None:
        query = query.where(AuditEventRow.created_at < upper)
        runs = runs.where(AssistantRunRow.created_at < upper)

    buckets: dict[bool, list[dict]] = {True: [], False: []}
    for row in session.scalars(query):
        detail = json.loads(row.detail_json or "{}")
        if detail.get("status") == "failed" and detail.get("promptTokens") is None:
            continue
        detail["_day"] = (row.created_at.replace(tzinfo=UTC).astimezone(CST).date().isoformat()
                          if row.created_at else "")
        buckets[bool(detail.get("isMock"))].append(detail)
    reply_runs = defaultdict(int)
    for run in session.scalars(runs):
        reply_runs[bool(run.is_mock)] += 1

    def bucket(calls: list[dict], replies: int) -> UsageBucket:
        stages: dict[str, dict] = defaultdict(lambda: defaultdict(float))
        models: dict[str, dict] = defaultdict(lambda: defaultdict(float))
        days: dict[str, int] = defaultdict(int)
        missing = 0
        costs: list[float | None] = []
        for call in calls:
            prompt, completion = call.get("promptTokens"), call.get("completionTokens")
            cached = call.get("cachedTokens") or 0
            if prompt is None or completion is None:
                missing += 1
            stage = stages[call.get("stage") or "other"]
            model = models[call.get("model") or "unknown"]
            for target in (stage, model):
                target["calls"] += 1
                target["prompt"] += prompt or 0
                target["completion"] += completion or 0
                target["cached"] += cached
            stage["latency"] += call.get("latencySeconds") or 0
            cost = estimate_cost(prices, call.get("model") or "", prompt=prompt, cached=cached, completion=completion)
            model.setdefault("costs", []).append(cost)
            costs.append(cost)
            days[call["_day"]] += 1
        prompt_total = int(sum(s["prompt"] for s in stages.values()))
        cached_total = int(sum(s["cached"] for s in stages.values()))
        total_cost = sum(costs) if costs and all(c is not None for c in costs) else None
        return UsageBucket(
            calls=len(calls), prompt_tokens=prompt_total,
            completion_tokens=int(sum(s["completion"] for s in stages.values())), cached_tokens=cached_total,
            cache_hit_rate=round(cached_total / prompt_total, 4) if prompt_total else None,
            calls_missing_tokens=missing, estimated_cost=round(total_cost, 6) if total_cost is not None else None,
            reply_runs=replies, calls_per_reply=round(len(calls) / replies, 2) if replies else None,
            cost_per_reply=round(total_cost / replies, 6) if total_cost is not None and replies else None,
            by_stage=[StageUsage(stage=name, calls=int(v["calls"]), prompt_tokens=int(v["prompt"]),
                                 completion_tokens=int(v["completion"]), cached_tokens=int(v["cached"]),
                                 latency_seconds=round(v["latency"], 3)) for name, v in sorted(stages.items())],
            by_model=[ModelUsage(model=name, calls=int(v["calls"]), prompt_tokens=int(v["prompt"]),
                                 completion_tokens=int(v["completion"]), cached_tokens=int(v["cached"]),
                                 estimated_cost=round(sum(v["costs"]), 6) if all(c is not None for c in v["costs"]) else None)
                      for name, v in sorted(models.items())],
            by_day=dict(sorted(days.items())),
        )

    agents = agent_usage(session, prices, lower=_bound(start, end=False), upper=_bound(end, end=True))
    live, mock = bucket(buckets[False], reply_runs[False]), bucket(buckets[True], reply_runs[True])
    live.by_agent, mock.by_agent = agents[False], agents[True]
    return UsageView(live=live, mock=mock, priced_models=sorted(prices))


def agent_usage(session: Session, prices: dict[str, ModelPrice], *, lower: datetime | None = None,
                upper: datetime | None = None) -> dict[bool, list[AgentUsage]]:
    """从追踪的模型调用跨度按所属 Agent 汇总；没有父 Agent 的调用记为 other。"""
    from app.audit.trace_models import AgentSpanRow

    query = select(AgentSpanRow).where(AgentSpanRow.kind.in_(("model_call", "model")))
    if lower is not None:
        query = query.where(AgentSpanRow.started_at >= lower)
    if upper is not None:
        query = query.where(AgentSpanRow.started_at < upper)
    calls = list(session.scalars(query))
    parents: dict[str, AgentSpanRow] = {}
    pending = {c.parent_span_id for c in calls if c.parent_span_id}
    while pending:  # 嵌套时一直向上找到非模型跨度
        rows = list(session.scalars(select(AgentSpanRow).where(AgentSpanRow.span_id.in_(pending))))
        parents.update({row.span_id: row for row in rows})
        pending = {row.parent_span_id for row in rows
                   if row.kind in {"model_call", "model"} and row.parent_span_id
                   and row.parent_span_id not in parents}

    def owner(span: AgentSpanRow) -> str:
        current = parents.get(span.parent_span_id or "")
        while current is not None and current.kind in {"model_call", "model"}:
            current = parents.get(current.parent_span_id or "")
        return current.name if current is not None else "other"

    groups: dict[bool, dict[str, dict]] = {True: defaultdict(lambda: {"calls": [], "traces": {}}),
                                           False: defaultdict(lambda: {"calls": [], "traces": {}})}
    for call in calls:
        group = groups[bool(call.is_mock)][owner(call)]
        group["calls"].append(call)
        moment = call.started_at.isoformat() if call.started_at else ""
        if moment >= group["traces"].get(call.trace_id, ""):
            group["traces"][call.trace_id] = moment
    out: dict[bool, list[AgentUsage]] = {}
    for mock, by_name in groups.items():
        rows = []
        for name, group in by_name.items():
            items = group["calls"]
            costs = [estimate_cost(prices, c.model_returned or c.model_requested or "", prompt=c.prompt_tokens,
                                   cached=c.cached_tokens, completion=c.completion_tokens) for c in items]
            latest = max(group["traces"].items(), key=lambda kv: kv[1])[0] if group["traces"] else None
            rows.append(AgentUsage(
                agent=name, calls=len(items), prompt_tokens=sum(c.prompt_tokens or 0 for c in items),
                completion_tokens=sum(c.completion_tokens or 0 for c in items),
                cached_tokens=sum(c.cached_tokens or 0 for c in items),
                latency_seconds=round(sum(c.duration_ms or 0 for c in items) / 1000, 3),
                estimated_cost=round(sum(costs), 6) if costs and all(c is not None for c in costs) else None,
                traces=len(group["traces"]), latest_trace_id=latest,
            ))
        out[mock] = sorted(rows, key=lambda row: (-row.prompt_tokens, row.agent))
    return out
