"""Local API acceptance for risk judgments; synthetic manual-mode conversation only."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy.engine import make_url

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services/api"))

from app.config import get_settings  # noqa: E402


def counts(conversation_id: str | None = None) -> dict:
    database = make_url(get_settings().sqlalchemy_url()).database
    if not database:
        raise ValueError("A file-backed local database is required")
    with sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True) as connection:
        return {
            "sourceRecords": connection.execute("SELECT COUNT(*) FROM service_source_record").fetchone()[0],
            "modelRuns": connection.execute(
                "SELECT COUNT(*) FROM service_assistant_run WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()[0],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    target = urlparse(args.api)
    if target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost"}:
        parser.error("Only the local demo API is allowed")
    run_key = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report = {
        "createdAt": datetime.now(UTC).isoformat(), "executionTarget": "local_http",
        "scope": "synthetic_manual_reception_api_acceptance", "checks": [],
        "limitations": [
            "This checks API behavior, not browser controls or responsive layout.",
            "Synthetic judgments are not expert labels or independent model-quality measurements.",
            "Only already-detected signals are reviewed; this does not measure missed risks or recall.",
        ],
    }
    success = False
    try:
        report["before"] = counts()
        with httpx.Client(base_url=args.api, trust_env=False, timeout=30) as client:
            def api(method, route, role="support", payload=None, expected=200):
                response = client.request(
                    method, route,
                    headers={"X-Demo-View-Role": role, "X-Demo-Operator": "G002"},
                    **({"json": payload} if payload is not None else {}),
                )
                if response.status_code != expected:
                    raise AssertionError(f"{route}: expected {expected}, got {response.status_code}")
                return response.json()

            health = api("GET", "/api/health")
            assert health["status"] == "ok" and health["runMode"] == "live"
            cid = api("POST", "/api/customer/conversations", "customer", {
                "customerId": f"JUDGMENT-EVAL-{run_key}",
            })["conversationId"]
            report["conversationId"] = cid
            api("POST", f"/api/customer/conversations/{cid}/handoff", "customer")

            def send(text, key):
                api("POST", f"/api/customer/conversations/{cid}/messages", "customer",
                    {"body": text, "clientMessageKey": key})

            def incident():
                return next(row for row in api("GET", "/api/support/desk/risks")
                            if cid in row["conversationIds"])

            send("人工模式接口走查，请核对已有记录", "baseline")
            send("还是没处理，我要投诉", "complaint")
            record = incident()
            signal = next(s for s in record["signals"] if s["riskType"] == "complaint_risk")
            route = f"/api/support/desk/risks/{record['incidentId']}/signals/{signal['alertId']}/judgment"
            first = api("POST", route, payload={
                "verdict": "confirmed", "note": "接口走查：原文存在明确投诉诉求",
                "expectedVersion": record["version"],
            })
            judgment = next(j for j in first["incident"]["judgments"] if j["alertId"] == signal["alertId"])
            assert first["incident"]["riskStatus"] == record["riskStatus"]
            assert first["incident"]["version"] == record["version"]
            assert judgment["actor"] == "G002" and not judgment["stale"] and judgment["evidence"]
            reread = api("GET", f"/api/support/desk/risks/{record['incidentId']}")
            assert reread["judgmentHistory"] == first["judgmentHistory"]
            report["checks"].append("judgment persisted without closing the risk")

            api("POST", route, payload={
                "verdict": "insufficient", "note": "旧页面重复提交",
                "expectedVersion": record["version"],
            }, expected=409)
            report["checks"].append("old judgment revision rejected")

            send("现在我还要向平台举报", "new-evidence")
            current = incident()
            latest = next(j for j in current["judgments"] if j["alertId"] == signal["alertId"])
            assert latest["stale"]
            refreshed = api("POST", route, payload={
                "verdict": "insufficient", "note": "接口走查：新投诉证据需重新人工核对",
                "expectedVersion": current["version"], "expectedJudgmentId": judgment["judgmentId"],
            })
            newest = next(j for j in refreshed["incident"]["judgments"] if j["alertId"] == signal["alertId"])
            assert not newest["stale"] and newest["supersedesId"] == judgment["judgmentId"]
            assert refreshed["incident"]["riskStatus"] == current["riskStatus"]
            report["checks"].append("new evidence requests re-review; correction appends history")

            exported = api("GET", "/api/support/desk/risk-judgments/export")
            assert exported["annotationScope"] == "demo_operator"
            assert exported["samplingScope"] == "detected_signals_only"
            assert exported["independentlyValidated"] is False
            report["judgments"] = [j for j in exported["judgments"] if j["alertId"] == signal["alertId"]]
            assert len(report["judgments"]) == 2
            report["checks"].append("export preserves both snapshots and annotation scope")
            report["after"] = counts(cid)
            assert report["after"]["sourceRecords"] == report["before"]["sourceRecords"]
            assert report["after"]["modelRuns"] == 0
            report["checks"].append("source record count unchanged; no model run for the test conversation")
            success = True
    except Exception as exc:
        report["error"] = type(exc).__name__
        report["detail"] = str(exc)[:300]
    report["passed"] = success
    destination = REPO / "evals/results" / f"loreal-risk-judgments-{run_key}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": success, "checks": report["checks"], "report": str(destination)},
                     ensure_ascii=False, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
