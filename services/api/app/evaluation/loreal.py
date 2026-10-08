"""Evaluation scoring, separate from reception validators and risk predictions."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def binary_metrics(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    tp = sum(row["expected"] and row["predicted"] for row in rows)
    fp = sum(not row["expected"] and row["predicted"] for row in rows)
    fn = sum(row["expected"] and not row["predicted"] for row in rows)
    tn = sum(not row["expected"] and not row["predicted"] for row in rows)
    return {
        "sampleCount": len(rows), "truePositive": tp, "falsePositive": fp,
        "falseNegative": fn, "trueNegative": tn,
        "recall": tp / (tp + fn) if tp + fn else None,
        "precision": tp / (tp + fp) if tp + fp else None,
        "accuracy": (tp + tn) / len(rows) if rows else None,
        "falsePositiveRate": fp / (fp + tn) if fp + tn else None,
        "missedCaseIds": [row["id"] for row in rows if row["expected"] and not row["predicted"]],
        "falsePositiveCaseIds": [row["id"] for row in rows if not row["expected"] and row["predicted"]],
    }


def set_metrics(rows: Iterable[dict[str, Any]], labels: list[str]) -> dict[str, Any]:
    rows = list(rows)
    return {
        "sampleCount": len(rows),
        "exactMatches": sum(set(row["expected"]) == set(row["predicted"]) for row in rows),
        "byLabel": {label: binary_metrics([
            {"id": row["id"], "expected": label in row["expected"], "predicted": label in row["predicted"]}
            for row in rows
        ]) for label in labels},
    }
