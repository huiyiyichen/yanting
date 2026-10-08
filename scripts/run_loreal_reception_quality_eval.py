"""Serial-turn live reception baseline; records failures without tuning the tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services/api"))

from app.config import get_settings  # noqa: E402
from app.evaluation.reception_quality import (  # noqa: E402
    blind_review_packet,
    configuration_receipt,
    conversation_for_turn,
    prior_case_exposure,
    recorded_runs,
    summarize_cases,
    turn_checks,
)


def await_terminal(api, conversation_id: str, *, window: float = 65) -> dict:
    deadline = time.perf_counter() + window
    while time.perf_counter() < deadline:
        items = api("GET", "/api/support/reception/queue")["items"]
        current = next(item for item in items if item["conversationId"] == conversation_id)
        if current["autoReplyStatus"] not in {"queued", "running"}:
            return current
        time.sleep(0.5)
    raise TimeoutError("No terminal reception status within observation window")


@contextmanager
def evaluation_client(api_url, settings, run_key, report, *, isolated):
    if not isolated:
        with httpx.Client(base_url=api_url, trust_env=False, timeout=30) as client:
            yield client, settings
        return
    from app.evaluation.reception_runtime import (
        configured_prompts,
        configured_settings,
        isolated_settings,
        prepare_runtime,
        reception_client,
    )
    from app.knowledge.ingest import active_snapshot_summary

    target_settings = isolated_settings(
        configured_settings(settings), REPO / "data/runtime" / f"reception-quality-{run_key}",
    )
    print("Preparing isolated real reception; main service and database are unchanged.", flush=True)
    runtime, metadata = prepare_runtime(
        target_settings, prompt_snapshot=configured_prompts(settings),
    )
    with reception_client(runtime) as client:
        # Exercise the normal publication API, including separately seeded product references.
        publication = client.post("/api/platform/knowledge/publish", headers={
            "X-Demo-View-Role": "support",
        })
        publication.raise_for_status()
        if not publication.json()["ok"]:
            raise ValueError("Reference knowledge publication failed")
        with runtime.new_session() as session:
            metadata["knowledgeAfterReferencePublication"] = active_snapshot_summary(session)
        metadata["referenceCatalogSha256"] = hashlib.sha256(
            (REPO / "data/knowledge/loreal/reference-products.json").read_bytes(),
        ).hexdigest()
        metadata["cnSourceReviewSha256"] = hashlib.sha256(
            (REPO / "data/knowledge/loreal/cn-product-source-review.json").read_bytes(),
        ).hexdigest()
        report.update({
            "executionTarget": "isolated_asgi", "runtimeBuildVerified": True,
            "runtime": metadata,
        })
        from app.domain.consumer_service.grounding import WORKFLOW_VERSION

        report["workflowVersion"] = WORKFLOW_VERSION
        report["limitations"].append(
            "Isolated ASGI uses current source and registry with saved effective prompts; "
            "it is not main-service deployment or a copy of user-edited knowledge.",
        )
        yield client, target_settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--ids", help="Comma-separated frozen case IDs; default all cases in the task file")
    parser.add_argument("--cases", type=Path, default=REPO / "evals/cases/loreal_reception_quality.json")
    parser.add_argument("--isolated", action="store_true",
                        help="Use current source and real providers in a new port-free ASGI runtime")
    parser.add_argument("--review-report", type=Path,
                        help="Export review input for an existing matching report; no model/runtime call")
    args = parser.parse_args()
    parsed = urlparse(args.api)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        parser.error("Only local demo targets are allowed")
    path = args.cases.resolve()
    if not path.is_relative_to(REPO / "evals/cases") or path.suffix != ".json":
        parser.error("Task files must be JSON inside evals/cases")
    raw = path.read_bytes()
    fixture_hash = hashlib.sha256(raw).hexdigest()
    fixture = json.loads(raw)
    if args.review_report:
        source_report = args.review_report.resolve()
        if (not source_report.is_relative_to(REPO / "evals/results")
                or source_report.suffix != ".json"):
            parser.error("Review reports must be JSON inside evals/results")
        saved = json.loads(source_report.read_text(encoding="utf-8"))
        if saved.get("caseSha256") != fixture_hash:
            parser.error("Review report does not match the unchanged task file")
        destination = source_report.with_name(f"{source_report.stem}-review-input.json")
        if destination.exists():
            parser.error("Review input already exists; refusing to replace it")
        packet = blind_review_packet(fixture, saved["cases"])
        packet["sourceReportSha256"] = hashlib.sha256(source_report.read_bytes()).hexdigest()
        destination.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Review input exported without model calls: {destination}")
        return 0
    cases = fixture["cases"]
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [case for case in cases if case["id"] in wanted]
        if wanted != {case["id"] for case in cases}:
            parser.error("Unknown case IDs")
    run_key = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    settings = get_settings()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    receipt = configuration_receipt(settings)
    if fixture["sourceSha256"] not in receipt["sourceFileHashes"]:
        parser.error("Official source does not match the frozen tasks")
    report = {
        "createdAt": datetime.now(UTC).isoformat(), "caseVersion": fixture["version"],
        "caseSha256": fixture_hash, "executionTarget": "local_http",
        "runtimeBuildVerified": False, "workflowVersion": None,
        "runHistoryScope": "database_records_present_at_end_of_observation",
        "annotation": fixture["annotation"], "configurationBefore": receipt,
        "plannedTurns": sum(len(case["turns"]) for case in cases), "cases": [],
        "limitations": [
            "Configuration receipts are read-only database observations, not proof of loaded server source.",
            "Engineering task labels and keyword checks are not independent semantic or empathy judgments.",
            "Each turn waits for completion; this is not a concurrency or load test.",
            "Token usage includes all recorded successful and failed runs, with unknown values retained.",
            "System latency is not human customer-service time; no monetary cost or productivity claim is made.",
        ],
    }
    report["previouslyObservedCaseIds"] = sorted(
        set(prior_case_exposure(REPO / "evals/results", fixture_hash)) & {case["id"] for case in cases},
    )
    report["evaluationPhase"] = "calibration_reused_tasks" if report["previouslyObservedCaseIds"] else "prospective_first_observation"
    with evaluation_client(args.api, settings, run_key, report, isolated=args.isolated) as (client, run_settings):
        def api(method, route, role="support", payload=None):
            response = client.request(method, route, headers={"X-Demo-View-Role": role},
                                      **({"json": payload} if payload is not None else {}))
            response.raise_for_status()
            return response.json()

        health = api("GET", "/api/health")
        if health["runMode"] != "live" or health["status"] != "ok":
            parser.error("A healthy live backend is required")
        for spec in cases:
            case = {key: spec[key] for key in ("id", "topic", "semanticGoals")}
            case["plannedTurns"] = len(spec["turns"])
            case["turns"] = []
            cid = None
            sessions = {}
            try:
                source_ids = spec.get("sourceConversationIds", [])
                if spec.get("sourceConversationId"):
                    source_ids = [*source_ids, spec["sourceConversationId"]]
                if source_ids:
                    contexts = [
                        api("GET", f"/api/support/conversations/{source_id}/service-context")
                        for source_id in dict.fromkeys(source_ids)
                    ]
                    case["businessFacts"] = {
                        "orders": list({item["orderId"]: item for context in contexts for item in context["orders"]}.values()),
                        "workOrders": list({item["workOrderId"]: item for context in contexts for item in context["workOrders"]}.values()),
                    }
                for index, turn in enumerate(spec["turns"]):
                    session_name = turn.get("session", "default")
                    customer_scope = turn.get("customerScope", "default")
                    cid = conversation_for_turn(api, sessions, turn, run_key, spec["id"])
                    case.setdefault("conversationId", cid)
                    observed = {
                        "index": index + 1, "customer": turn["body"],
                        "session": session_name, "customerScope": customer_scope, "conversationId": cid,
                        "expectModelReply": turn["expectModelReply"],
                    }
                    case["turns"].append(observed)
                    started = time.perf_counter()
                    try:
                        initial_ids = {
                            item["messageId"] for item in
                            api("GET", f"/api/customer/conversations/{cid}/messages", "customer")
                        }
                        api("POST", f"/api/customer/conversations/{cid}/messages", "customer", {
                            "body": turn["body"], "clientMessageKey": f"quality-{index}",
                        })
                        current = await_terminal(api, cid)
                        # A bounded extra observation catches immediate late deliveries
                        # after a handoff, not every possible delayed worker completion.
                        if not turn["expectModelReply"]:
                            time.sleep(2)
                        messages = api("GET", f"/api/customer/conversations/{cid}/messages", "customer")
                        assistant = api("GET", f"/api/support/conversations/{cid}/assistant")
                        memory = api("GET", f"/api/support/reception/{cid}/memory")
                        assessment = api("GET", f"/api/support/desk/breakpoints/{cid}")
                        observed.update({
                            "mode": current["serviceMode"], "jobStatus": current["autoReplyStatus"],
                            "handoffReason": current["handoffReason"],
                            "reply": [item["body"] for item in messages
                                      if item["senderRole"] == "assistant" and item["messageId"] not in initial_ids],
                            "assistant": assistant, "memory": memory,
                            "breakpointAssessment": assessment,
                        })
                        observed["checks"] = turn_checks(turn, observed)
                        print(f'{spec["id"]}/{index + 1}: mode={observed["mode"]} '
                              f'replies={len(observed["reply"])} '
                              f'checks={sum(observed["checks"].values())}/{len(observed["checks"])}',
                              flush=True)
                        if turn["expectModelReply"] and current["serviceMode"] != "autonomous":
                            case["remainingTurnsNotRunReason"] = "unexpected_handoff_no_forced_resume"
                            break
                    except Exception as exc:
                        observed["error"] = type(exc).__name__
                        case["remainingTurnsNotRunReason"] = "api_or_observation_error"
                        break
                    finally:
                        observed["elapsedSeconds"] = round(time.perf_counter() - started, 3)
            except Exception as exc:
                case["setupError"] = type(exc).__name__
            finally:
                case["sessions"] = sessions
                case["runHistory"] = [
                    {**run, "conversationId": value["conversationId"]}
                    for value in sessions.values()
                    for run in recorded_runs(run_settings, value["conversationId"])
                ]
                report["cases"].append(case)
    report["configurationAfter"] = configuration_receipt(settings)
    report["configurationUnchanged"] = report["configurationBefore"] == report["configurationAfter"]
    report["fixtureUnchanged"] = path.read_bytes() == raw
    report["summary"] = summarize_cases(report["cases"])
    report["summary"]["setupErrors"] = sum("setupError" in case for case in report["cases"])
    destination = REPO / "evals/results" / f"loreal-reception-quality-{run_key}.json"
    packet_path = destination.with_name(f"loreal-reception-quality-{run_key}-review-input.json")
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    packet_path.write_text(json.dumps(blind_review_packet(fixture, report["cases"]),
                                      ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(destination), "reviewInput": str(packet_path),
                      "configurationUnchanged": report["configurationUnchanged"],
                      "fixtureUnchanged": report["fixtureUnchanged"], "summary": report["summary"]},
                     ensure_ascii=False, indent=2))
    return 0 if (report["configurationUnchanged"] and report["fixtureUnchanged"]
                 and report["summary"]["casesAllMechanicalChecks"] == len(cases)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
