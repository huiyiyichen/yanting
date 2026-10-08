"""Evaluate deterministic evidence gates for semantic service breakpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services/api"))

from app.domain.consumer_service.service_breakpoints import (  # noqa: E402
    VERSION,
    qualify_findings,
)
from app.evaluation.loreal import binary_metrics  # noqa: E402
from app.schemas.grounding import GroundingSource  # noqa: E402
from app.schemas.service_breakpoints import BreakpointCandidate  # noqa: E402


def context_from(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        conversation_id=raw["conversationId"],
        orders=[
            SimpleNamespace(
                order_id=item["orderId"],
                conversation_id=item["conversationId"],
            )
            for item in raw.get("orders", [])
        ],
        work_orders=[
            SimpleNamespace(
                order_id=item.get("orderId"),
                conversation_id=item["conversationId"],
            )
            for item in raw.get("workOrders", [])
        ],
    )


def evaluate_case(row: dict) -> dict:
    sources = [GroundingSource.model_validate(item) for item in row["sources"]]
    statements = [
        source for source in sources
        if source.source_id in set(row.get("statements", []))
    ]
    candidates = []
    validation_error = None
    try:
        candidates = [BreakpointCandidate.model_validate(row["candidate"])]
    except Exception as exc:
        validation_error = f"{type(exc).__name__}: {str(exc)[:240]}"
    findings, issues = ([], [validation_error]) if validation_error else qualify_findings(
        candidates, sources, statements, context_from(row["context"]),
    )
    predicted = bool(findings)
    return {
        **row,
        "predicted": predicted,
        "predictedKinds": sorted({finding.kind for finding in findings}),
        "issues": issues,
        "validationError": validation_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=REPO / "evals/cases/loreal_breakpoints.json")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    rows = [evaluate_case(row) for row in cases["cases"]]
    scored = [{"id": row["id"], "expected": row["expected"], "predicted": row["predicted"]} for row in rows]
    report = {
        "createdAt": datetime.now(UTC).isoformat(),
        "mode": "offline_deterministic_evidence_gate",
        "caseVersion": cases["version"],
        "caseSha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "annotation": cases["annotation"],
        "scope": cases["scope"],
        "ruleVersion": VERSION,
        "python": platform.python_version(),
        "implementationSha256": {
            name: hashlib.sha256(
                (REPO / "services/api/app/domain/consumer_service" / name).read_bytes()
            ).hexdigest()
            for name in ("service_breakpoints.py", "grounding.py")
        },
        "metrics": binary_metrics(scored),
        "byKind": {
            kind: binary_metrics([
                row for row in scored
                if next(case for case in cases["cases"] if case["id"] == row["id"])["expectedKind"] == kind
            ])
            for kind in ("repeated_question", "unmet_promise", "resolution_mismatch")
        },
        "cases": rows,
        "limitations": [
            "This evaluates deterministic evidence and safety gates, not model semantic similarity judgments.",
            "The frozen cases are engineering annotations, not independent human expert labels.",
            "A model may still propose the wrong topic with valid quotes; that requires a separate semantic review set.",
            "No HTTP service, database, embedding, or model provider is used.",
        ],
    }
    destination = REPO / "evals/results" / f"loreal-breakpoints-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(destination), "metrics": report["metrics"],
                      "byKind": report["byKind"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
