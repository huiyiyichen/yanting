"""Evaluate source checks and, optionally, the configured live semantic verifier."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.domain.consumer_service.grounded_workflow import (  # noqa: E402
    GroundedDraft, VERIFIER_PROMPT, Verification,
)
from app.domain.consumer_service.grounding import validate_claims  # noqa: E402
from app.evaluation.loreal import binary_metrics  # noqa: E402
from app.schemas.grounding import GroundingClaim, GroundingSource  # noqa: E402


def model_runtime():
    from app.config import get_settings
    from app.db import build_engine, build_session_factory
    from app.integrations.embedding_provider import MockEmbeddingProvider
    from app.integrations.model_provider import OpenAICompatibleModelProvider
    from app.runtime import RuntimeContext

    settings = get_settings()
    engine = build_engine(settings)
    runtime = RuntimeContext(
        settings=settings, engine=engine, session_factory=build_session_factory(engine),
        model_provider=OpenAICompatibleModelProvider.from_settings(settings),
        embedding_provider=MockEmbeddingProvider(reason="not used by verifier evaluation"),
    )
    runtime.apply_runtime_settings()
    if not runtime.model_provider.available() or settings.run_mode != "live":
        engine.dispose()
        raise ValueError("Live model unavailable; no successful mock fallback")
    return runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=REPO / "evals/cases/loreal_grounding.json")
    parser.add_argument("--live", action="store_true", help="One real verifier request per case; no customer messages")
    parser.add_argument("--ids", help="Comma-separated IDs for targeted checks; omitted means all cases")
    args = parser.parse_args()
    fixture = json.loads(args.cases.read_text(encoding="utf-8"))
    sources = [GroundingSource.model_validate(s) for s in fixture["sources"]]
    catalog = {s.source_id: s for s in sources}
    selected = fixture["cases"]
    if args.ids:
        ids = set(args.ids.split(","))
        selected = [case for case in selected if case["id"] in ids]
        if {case["id"] for case in selected} != ids:
            parser.error("Unknown case IDs")
    rows, live_rows = [], []
    runtime = model_runtime() if args.live else None
    try:
        for case in selected:
            claims = [GroundingClaim(text=case["body"], source_refs=case["refs"])] if case["refs"] else []
            issues = validate_claims(case["body"], claims, catalog)
            rows.append({**case, "predicted": not issues, "issues": issues})
            if runtime is None:
                continue
            from app.integrations.model_provider import ChatMessage

            draft = GroundedDraft(
                current_question="核对这条客服陈述是否有依据",
                reply_suggestions=[{"style": "recommended", "body": case["body"], "claims": claims}],
            )
            try:
                result = runtime.model_provider.complete([
                    ChatMessage("system", VERIFIER_PROMPT),
                    ChatMessage("user", json.dumps({
                        "sourceCatalog": [s.dump() for s in sources], "draft": draft.model_dump(mode="json"),
                        "latestCustomerMessage": "请核对订单和商品资料", "recentConversation": [],
                    }, ensure_ascii=False)),
                ], temperature=0, max_tokens=700, json_mode=False)
                if result.is_mock:
                    raise ValueError("Live evaluation cannot accept mock verification")
                verdict = Verification.model_validate_json(result.text)
                supported = verdict.supported and not verdict.issues
                live_rows.append({**case, "predicted": supported, "issues": verdict.issues,
                                  "model": result.model, "promptTokens": result.prompt_tokens,
                                  "completionTokens": result.completion_tokens, "latencySeconds": result.latency_seconds})
            except Exception as exc:
                # Errors remain in the denominator but are not semantic rejection successes.
                live_rows.append({**case, "predicted": None, "errorCode": type(exc).__name__})
            print(f'{case["id"]}: completed', flush=True)
    finally:
        if runtime is not None:
            runtime.engine.dispose()
    live_valid = [r for r in live_rows if r["predicted"] is not None]
    by_id = {r["id"]: r for r in rows}
    combined = [{**r, "predicted": bool(r["predicted"] and by_id[r["id"]]["predicted"])} for r in live_valid]
    report = {
        "createdAt": datetime.now(UTC).isoformat(), "caseVersion": fixture["version"],
        "caseSha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(), "annotation": fixture["annotation"],
        "revisionNote": fixture.get("revisionNote"), "selectedCaseIds": [case["id"] for case in selected],
        "mode": "live_verifier" if args.live else "offline_validator", "python": platform.python_version(),
        "validatorSha256": hashlib.sha256((REPO / "services/api/app/domain/consumer_service/grounding.py").read_bytes()).hexdigest(),
        "verifierPromptSha256": hashlib.sha256(VERIFIER_PROMPT.encode()).hexdigest(),
        "deterministic": {"metrics": binary_metrics(rows), "cases": rows},
        "live": {"requested": len(live_rows), "validResponses": len(live_valid),
                 "errors": len(live_rows) - len(live_valid),
                 "metricsAmongValidResponses": binary_metrics(live_valid), "cases": live_rows,
                 "combinedGateMetricsAmongValidResponses": binary_metrics(combined),
                 "falseAccepts": [r["id"] for r in live_valid if not r["expected"] and r["predicted"]],
                 "trueRejections": [r["id"] for r in live_valid if not r["expected"] and not r["predicted"]]},
        "limitations": [
            "Semantic verifier is evaluated against frozen external-to-output labels, but remains the same model used for drafting.",
            "This measures acceptance of constructed claims, not full automatic reception or independent human semantic grading.",
            "Valid-response metrics exclude errors; requested/valid/errors are separately reported.",
            "Cases adjusted against observed failures are calibration, not untouched holdout evidence.",
        ],
    }
    destination = REPO / "evals/results" / f"loreal-grounding-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(destination), "deterministic": report["deterministic"]["metrics"],
                      "live": {k: v for k, v in report["live"].items() if k != "cases"}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
