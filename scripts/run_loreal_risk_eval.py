"""Replay frozen risk labels without changing the runtime DB or calling models."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "api"))

from app.domain.consumer_service.risk_rules import (  # noqa: E402
    RULE_VERSION, RuleMessage, RuleTicket, compute_signals, utc,
)
from app.evaluation.loreal import binary_metrics, set_metrics  # noqa: E402

LABELS = ["emotion_escalation", "complaint_risk"]
START = datetime(2026, 5, 1)


def predicted(messages, tickets=()):
    return compute_signals(list(messages), list(tickets), now=START + timedelta(days=30),
                           source_clock=START + timedelta(days=7), repeat_hours=72, overdue_hours=48)


def evaluate(cases: dict, source: Path) -> dict:
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if source_hash != cases["sourceSha256"]:
        raise ValueError("Official source hash differs from frozen annotation source")
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        table = workbook["聊天记录"].values
        header = next(table)
        conversations = defaultdict(list)
        for values in table:
            row = dict(zip(header, values, strict=True))
            if row["角色"] != "买家":
                continue
            cid = row["会话ID"]
            conversations[cid].append(RuleMessage(
                str(row["message_id"]), cid, row["买家昵称"], row["message_text"] or "",
                utc(row["发送时间"], source=True), row["关联订单号"], row["店铺"],
            ))
    finally:
        workbook.close()
    sampled = sorted(conversations, key=lambda k: hashlib.sha256(("loreal-eval-v1:" + k).encode()).hexdigest())[:24]
    if {row["id"] for row in cases["official"]} != set(sampled):
        raise ValueError("Official sample no longer matches declared sampling policy")
    official = []
    for row in cases["official"]:
        signals = predicted(conversations[row["id"]])
        observed = [signal.kind.value for signal in signals]
        official.append({**row, "expected": row["escalation"],
                         "predicted": "emotion_escalation" in observed, "observedTypes": observed})
    challenge = []
    for row in cases["challenge"]:
        messages = [RuleMessage(f'{row["id"]}-{i}', row["id"], "fixture-buyer", body,
                                START + timedelta(minutes=i)) for i, body in enumerate(row["messages"])]
        observed = sorted({signal.kind.value for signal in predicted(messages)} & set(LABELS))
        challenge.append({**row, "predicted": observed})
    structured = []
    for row in cases["structured"]:
        messages, tickets = [], []
        kind = row["kind"]
        target = "repeated_contact" if kind == "contact" else "adverse_reaction" if kind == "reaction" else "repeated_refund"
        if kind == "contact":
            messages = [
                RuleMessage("first", "c1", "buyer", "查询订单", START, shop="shop"),
                RuleMessage("second", "c2", "buyer", "查询订单", START + timedelta(hours=row["hours"]),
                            shop="shop" if row["sameShop"] else "other"),
            ]
        else:
            details = ([{"paymentType": value} for value in row["types"]] if kind == "refund" else
                       [{"refundId": value} for value in row["refundIds"]] if kind == "return" else
                       [{"symptomDescription": "自述红肿刺痛", "soughtMedicalCare": "是"}])
            for i, detail in enumerate(details):
                tickets.append(RuleTicket(
                    f"t{i}", f"t{i}", "c1", "buyer",
                    {"refund": "offline_payment", "return": "return_refund", "reaction": "adverse_reaction"}[kind],
                    row.get("orders", ["o1"] * len(details))[i], "in_progress", START, detail=detail,
                ))
        observed = sorted({signal.kind.value for signal in predicted(messages, tickets)})
        structured.append({**row, "predicted": target in observed, "observedTypes": observed})
    return {
        "officialEmotion": {"metrics": binary_metrics(official), "cases": official},
        "challenge": {"metrics": set_metrics(challenge, LABELS), "cases": challenge},
        "structured": {"metrics": binary_metrics(structured), "cases": structured},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=REPO / "evals/cases/loreal_risk.json")
    parser.add_argument("--source", type=Path, default=REPO / "data/source/loreal-official-mock/source-b5ac027e863c5580dab39c8f459e4698d65e9fbec29832c9915448f2087307b7.xlsx")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    report = {
        "createdAt": datetime.now(UTC).isoformat(), "mode": "offline_rules", "model": None,
        "caseVersion": cases["version"], "caseSha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "annotation": cases["annotation"], "sampling": cases["officialSampling"],
        "sourceSha256": cases["sourceSha256"], "ruleVersion": RULE_VERSION, "python": platform.python_version(),
        "implementationSha256": {name: hashlib.sha256((REPO / "services/api/app/domain/consumer_service" / name).read_bytes()).hexdigest()
                                 for name in ("risk_rules.py", "emotion.py")},
        "policy": {"repeatContactHours": 72, "sourceOverdueHours": 48, "emotion": "ever escalated within conversation, not latest-active-risk"},
        "limitations": [
            "Labels are engineering AI-assisted judgments, not independent human experts.",
            "Official conversations are fictional; 24 hash-selected samples do not establish production performance.",
            "Constructed challenge cases become calibration after fixes based on their failures.",
            "Risk rules run without a model; these results do not establish model emotion accuracy or external complaint monitoring.",
        ],
        **evaluate(cases, args.source),
    }
    destination = REPO / "evals/results" / f"loreal-risk-{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(destination), "official": report["officialEmotion"]["metrics"],
                      "challenge": report["challenge"]["metrics"], "structured": report["structured"]["metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
