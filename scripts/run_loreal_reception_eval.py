"""Live local reception evaluation; creates explicitly marked demo conversations."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.domain.consumer_service.grounding import WORKFLOW_VERSION  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--ids", help="Targeted comma-separated IDs, default all cases")
    parser.add_argument("--isolated", action="store_true",
                        help="Use latest source in a new live ASGI runtime; no listening port or main-service restart")
    args = parser.parse_args()
    if not args.api.startswith(("http://127.0.0.1:", "http://localhost:")):
        parser.error("Reception evaluation must use the local demo")
    path = REPO / "evals/cases/loreal_reception.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    selected = fixture["cases"]
    if args.ids:
        wanted = set(args.ids.split(","))
        selected = [r for r in selected if r["id"] in wanted]
        if {r["id"] for r in selected} != wanted:
            parser.error("Unknown case IDs")
    run_key = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    rows = []
    runtime = None
    metadata = {"executionTarget": "local_http", "api": args.api, "runtimeBuildVerified": False}
    with contextlib.ExitStack() as stack:
        if args.isolated:
            from app.config import get_settings
            from app.evaluation.reception_runtime import (
                configured_prompts,
                configured_settings,
                isolated_settings,
                prepare_runtime,
                reception_client,
            )
            base_settings = get_settings()
            prompt_snapshot = configured_prompts(base_settings)
            settings = isolated_settings(
                configured_settings(base_settings),
                REPO / "data/runtime" / f"reception-eval-{run_key}",
            )
            print("Preparing isolated official facts and real knowledge index; no main-service writes.", flush=True)
            runtime, metadata = prepare_runtime(settings, prompt_snapshot=prompt_snapshot)
            stack.callback(runtime.close)
            client = stack.enter_context(reception_client(runtime))
            metadata["runtimeBuildVerified"] = True
        else:
            client = stack.enter_context(httpx.Client(base_url=args.api, timeout=60, trust_env=False))

        def api(method, route, role="support", payload=None):
            response = client.request(method, route, headers={"X-Demo-View-Role": role},
                                      **({"json": payload} if payload is not None else {}))
            response.raise_for_status()
            return response.json()

        health = api("GET", "/api/health")
        if health.get("runMode") != "live":
            parser.error("Live runtime required; no mock fallback")
        for case in selected:
            row = {"id": case["id"], "expected": case, "reviewStatus": "pending_independent_semantic_review"}
            start = time.perf_counter()
            try:
                created = api("POST", "/api/customer/conversations", "customer",
                              {"customerId": f'EVAL-{run_key}-{case["id"]}'})
                cid = row["conversationId"] = created["conversationId"]
                initial = api("GET", f"/api/customer/conversations/{cid}/messages", "customer")
                initial_ids = {r["messageId"] for r in initial}
                for index, text in enumerate(case["messages"]):
                    api("POST", f"/api/customer/conversations/{cid}/messages", "customer",
                        {"body": text, "clientMessageKey": f"eval-{index}"})
                deadline = time.perf_counter() + 60
                current = None
                while time.perf_counter() < deadline:
                    snapshot = api("GET", "/api/support/reception/queue")
                    current = next(item for item in snapshot["items"] if item["conversationId"] == cid)
                    if current["autoReplyStatus"] not in {"queued", "running"}:
                        break
                    time.sleep(1)
                if current is None or current["autoReplyStatus"] in {"queued", "running"}:
                    raise TimeoutError("Reception did not finish within evaluation observation window")
                messages = api("GET", f"/api/customer/conversations/{cid}/messages", "customer")
                assistant = api("GET", f"/api/support/conversations/{cid}/assistant")
                memory = api("GET", f"/api/support/reception/{cid}/memory")
                replies = [m["body"] for m in messages if m["senderRole"] == "assistant" and m["messageId"] not in initial_ids]
                if assistant and assistant["isMock"]:
                    raise ValueError("Live result cannot be mock")
                row.update({
                    "mode": current["serviceMode"], "autoReplyStatus": current["autoReplyStatus"],
                    "modeMatches": current["serviceMode"] == case["mode"], "reply": replies,
                    "intent": assistant.get("intent") if assistant else None,
                    "intentMatches": assistant.get("intent") == case["intent"] if assistant and case["intent"] else None,
                    "memory": memory, "verified": assistant.get("verificationStatus") if assistant else None,
                    "requiredMemoryPresent": set(case["requiredMemory"]) <= {m["category"] for m in memory["items"]},
                    "model": assistant.get("modelId") if assistant else None,
                    "promptVersion": assistant.get("promptVersion") if assistant else None,
                    "cacheStale": assistant.get("stale") if assistant else None,
                    "usage": assistant.get("modelUsage") if assistant else None,
                    "workflow": assistant.get("workflowSteps") if assistant else [],
                    "replySuggestions": assistant.get("replySuggestions") if assistant else [],
                    "groundingSources": assistant.get("groundingSources") if assistant else [],
                })
            except Exception as exc:
                row["errorCode"] = type(exc).__name__
            if runtime is not None and row.get("conversationId"):
                from app.evaluation.reception_runtime import run_history

                row["runHistory"] = run_history(runtime, row["conversationId"])
            row["elapsedSeconds"] = round(time.perf_counter() - start, 3)
            rows.append(row)
            print(f'{case["id"]}: mode={row.get("mode", "error")} replyCount={len(row.get("reply", []))}', flush=True)
    report = {
        "createdAt": datetime.now(UTC).isoformat(), "caseVersion": fixture["version"],
        "caseSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "workflowVersion": WORKFLOW_VERSION if args.isolated else None,
        "evaluatorWorkflowVersion": WORKFLOW_VERSION, "runtime": metadata,
        "python": platform.python_version(), "mode": "live_reception", "sampleCount": len(rows),
        "errors": sum("errorCode" in row for row in rows), "modeMatches": sum(row.get("modeMatches", False) for row in rows),
        "intentEligible": sum(row.get("intentMatches") is not None for row in rows),
        "intentMatches": sum(row.get("intentMatches") is True for row in rows),
        "annotation": fixture["annotation"], "cases": rows,
        "limitations": [
            "Six engineered tasks are not a statistically representative accuracy estimate.",
            "Mode and intent checks are mechanical; semantic support and empathy need separate review.",
            "No human task-time baseline is measured; elapsedSeconds is system latency, not customer-service productivity.",
            "No refunds, payments or external order changes are executed; data is fictional and local.",
            "Isolated ASGI checks latest source, not deployment of the currently running main service.",
            "Isolated mode snapshots saved effective reception prompts, while using current fixed safety constraints and the fixture knowledge manifest.",
            "Local evaluator version alone does not establish the HTTP server's running workflow version.",
        ],
    }
    destination = REPO / "evals/results" / f"loreal-reception-{run_key}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, ensure_ascii=False, indent=2))
    print(f"Report: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
