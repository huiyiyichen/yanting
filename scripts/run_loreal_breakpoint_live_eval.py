"""Run a small live HTTP evaluation for semantic service breakpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services/api"))

from app.domain.consumer_service.grounding import WORKFLOW_VERSION  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--ids", help="Comma-separated case IDs")
    args = parser.parse_args()
    if not args.api.startswith(("http://127.0.0.1:", "http://localhost:")):
        parser.error("Live breakpoint evaluation must use the local demo")

    cases_path = REPO / "evals/cases/loreal_breakpoint_live.json"
    fixture = json.loads(cases_path.read_text(encoding="utf-8"))
    selected = fixture["cases"]
    if args.ids:
        wanted = set(args.ids.split(","))
        selected = [case for case in selected if case["id"] in wanted]
        if {case["id"] for case in selected} != wanted:
            parser.error("Unknown case IDs")

    run_key = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    rows = []
    with httpx.Client(base_url=args.api, timeout=120, trust_env=False) as client:
        def api(method: str, route: str, role: str = "support", payload=None):
            headers = {"X-Demo-View-Role": role}
            if role == "support":
                headers["X-Demo-Operator"] = "G001"
            response = client.request(
                method, route, headers=headers,
                **({"json": payload} if payload is not None else {}),
            )
            response.raise_for_status()
            return response.json()

        health = api("GET", "/api/health")
        if health.get("runMode") != "live":
            parser.error("Live runtime required; no mock fallback")

        for case in selected:
            row = {
                "id": case["id"],
                "expected": case,
                "reviewStatus": "pending_independent_semantic_review",
            }
            started = time.perf_counter()
            try:
                created = api(
                    "POST", "/api/customer/conversations", "customer",
                    {"customerId": f"BREAKPOINT-EVAL-{run_key}-{case['id']}"},
                )
                conversation_id = row["conversationId"] = created["conversationId"]
                api("POST", f"/api/customer/conversations/{conversation_id}/handoff", "customer")
                for index, text in enumerate(case["messages"]):
                    api(
                        "POST", f"/api/customer/conversations/{conversation_id}/messages",
                        "customer",
                        {"body": text, "clientMessageKey": f"breakpoint-eval-{index}"},
                    )
                assessment = api(
                    "POST", f"/api/support/desk/breakpoints/{conversation_id}",
                )
                findings = assessment.get("findings", [])
                kinds = sorted({item["kind"] for item in findings})
                row.update({
                    "assessment": assessment,
                    "predictedFindings": bool(findings),
                    "predictedKinds": kinds,
                    "findingsCount": len(findings),
                    "expectedFindingsMatch": bool(findings) == case["expectedFindings"],
                    "expectedKindsMatch": set(kinds) == set(case["expectedKinds"]),
                    "model": assessment.get("modelId"),
                    "isMock": assessment.get("isMock"),
                    "usage": assessment.get("modelUsage"),
                    "workflow": assessment.get("workflowSteps", []),
                })
                if row["isMock"]:
                    raise ValueError("Live result cannot be mock")
            except Exception as exc:
                row["errorCode"] = type(exc).__name__
                row["error"] = str(exc)[:500]
            row["elapsedSeconds"] = round(time.perf_counter() - started, 3)
            rows.append(row)
            print(
                f"{case['id']}: findings={row.get('findingsCount', 'error')} "
                f"kinds={row.get('predictedKinds', [])}",
                flush=True,
            )

    report = {
        "createdAt": datetime.now(UTC).isoformat(),
        "mode": "live_http_breakpoint",
        "executionTarget": "main_local_http",
        "caseVersion": fixture["version"],
        "caseSha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "workflowVersion": WORKFLOW_VERSION,
        "runtime": {
            "api": args.api,
            "model": next((row.get("model") for row in rows if row.get("model")), None),
            "isMock": any(row.get("isMock") for row in rows),
        },
        "sampleCount": len(rows),
        "errors": sum("errorCode" in row for row in rows),
        "findingMatches": sum(row.get("expectedFindingsMatch", False) for row in rows),
        "kindMatches": sum(row.get("expectedKindsMatch", False) for row in rows),
        "annotation": fixture["annotation"],
        "cases": rows,
        "limitations": [
            "Three engineered live samples are not a representative accuracy estimate.",
            "Expected labels require independent semantic review; they are not human expert labels.",
            "This evaluates the running main service and may add explicitly marked demo conversations.",
            "No refund, payment, order, ticket or other real business action is executed.",
        ],
    }
    destination = REPO / "evals/results" / f"loreal-breakpoint-live-{run_key}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report: {destination}")
    print(json.dumps({
        "sampleCount": report["sampleCount"],
        "errors": report["errors"],
        "findingMatches": report["findingMatches"],
        "kindMatches": report["kindMatches"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
