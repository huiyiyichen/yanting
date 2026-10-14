"""模型用量与成本统计（改进方案 P1-7）。

数据来自审计中的 model_call 事件（每次实际模型调用一条，含节点、型号、Token、缓存命中）。
Mock 与 live 分开统计；价格表按模型 ID 配置（每百万 Token 元），未配置的模型不估算成本。
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta, timezone

from pydantic import BaseModel, ConfigDict, ValidationError
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
    runs = select(AssistantRunRow).where(AssistantRunRow.status.in_(("verified", "partial")))
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

    return UsageView(live=bucket(buckets[False], reply_runs[False]), mock=bucket(buckets[True], reply_runs[True]),
                     priced_models=sorted(prices))
