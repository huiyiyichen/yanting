"""编排基线（多 Agent 设计 阶段 0 第 8 项 / 阶段 6 对比）。

对本地服务逐条跑评测集里的消费者消息，以“客服生成”方式取回复建议，读取每次生成的
Agent 追踪，汇总：可用率、待确认率、调用数、输入/输出 Token、端到端耗时 p50/p95。

只有 /api/health 报告 runMode=live 时结果才算 live；Mock 结果会在报告里标 isMock=true，
只用来验证流程与调用结构，不代表回复质量。

用法（仓库根，先启动本地服务）：
  services/api/.venv/bin/python scripts/run_orchestration_baseline.py --label single
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
CASE_FILES = ("loreal_reception.json", "loreal_grounding.json", "loreal_personalization.json")


def cases() -> list[dict]:
    out = []
    for name in CASE_FILES:
        path = REPO / "evals" / "cases" / name
        if not path.exists():
            continue
        for case in json.loads(path.read_text(encoding="utf-8")).get("cases", []):
            messages = case.get("messages") or ([case["message"]] if case.get("message") else [])
            if messages:
                out.append({"id": f"{path.stem}:{case.get('id')}", "messages": messages})
    return out


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--label", default="single", help="single / multi")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if not args.api.startswith(("http://127.0.0.1:", "http://localhost:")):
        parser.error("Baseline must use the local demo")
    client = httpx.Client(base_url=args.api, timeout=120, trust_env=False)

    def api(method, route, role="support", payload=None):
        response = client.request(method, route, headers={"X-Demo-View-Role": role},
                                  **({"json": payload} if payload is not None else {}))
        return response

    health = api("GET", "/api/health").json()
    is_mock = health.get("runMode") != "live"
    run_key = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    rows = []
    for case in cases()[: args.limit or None]:
        row: dict = {"id": case["id"]}
        cid = api("POST", "/api/customer/conversations", "customer",
                  {"customerId": f"BASE-{run_key}-{case['id']}"[:60]}).json()["conversationId"]
        api("POST", f"/api/support/reception/{cid}/service-mode", payload={"mode": "operator_assisted"})
        for index, text in enumerate(case["messages"]):
            api("POST", f"/api/customer/conversations/{cid}/messages", "customer",
                {"body": text, "clientMessageKey": f"base-{index}"})
        started = time.perf_counter()
        response = api("POST", f"/api/support/reception/{cid}/assistant")
        row["wallMs"] = round((time.perf_counter() - started) * 1000)
        row["httpStatus"] = response.status_code
        if response.status_code == 200:
            view = response.json()
            row["verificationStatus"] = view.get("verificationStatus")
            trace_id = (view.get("modelUsage") or {}).get("traceId")
        else:
            trace_id = None
            listed = api("GET", f"/api/platform/traces?conversationId={cid}&limit=1").json()
            if listed.get("items"):
                trace_id = listed["items"][0]["traceId"]
        if trace_id:
            detail = api("GET", f"/api/platform/traces/{trace_id}").json()
            row["traceId"], row["totals"] = trace_id, detail.get("totals", {})
            row["orchestration"] = detail.get("orchestration")
        rows.append(row)
        print(case["id"], row.get("httpStatus"), row.get("verificationStatus"), row.get("wallMs"), flush=True)

    usable = [r for r in rows if r.get("verificationStatus") in {"verified", "partial", "needs_review"}]
    walls = [r["wallMs"] for r in rows]
    totals = [r.get("totals", {}) for r in rows]

    def mean(key: str):
        values = [t[key] for t in totals if t.get(key) is not None]
        return round(statistics.mean(values), 1) if values else None

    report = {
        "label": args.label, "isMock": is_mock, "runMode": health.get("runMode"),
        "note": "Mock 结果只验证流程与调用结构，不代表回复质量" if is_mock else "live",
        "generatedAt": run_key, "cases": len(rows),
        "usableRate": round(len(usable) / len(rows), 4) if rows else None,
        "verifiedRate": round(sum(r.get("verificationStatus") == "verified" for r in rows) / len(rows), 4)
        if rows else None,
        "needsReviewRate": round(sum(r.get("verificationStatus") == "needs_review" for r in rows) / len(rows), 4)
        if rows else None,
        "wallMsP50": pct(walls, 0.5), "wallMsP95": pct(walls, 0.95),
        "meanCalls": mean("calls"), "meanPromptTokens": mean("promptTokens"),
        "meanCompletionTokens": mean("completionTokens"), "meanCachedTokens": mean("cachedTokens"),
        "rows": rows,
    }
    out = REPO / "evals" / "results" / f"orchestration-baseline-{args.label}-{run_key}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
