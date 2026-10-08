"""检索模式对照：dense-only / sparse-only / hybrid（工程规范第 12.5 节）。

要求：比较 dense-only 与混合检索，保留同一输入、正确证据标签、召回结果、
模型/索引版本和时延。

为什么必须实测：Qdrant 的 RRF 只是把两路排名融合，**不保证**混合一定优于单路。
若校准集显示混合没有增益，就应如实报告，而不是因为「我用了混合检索」就宣称更好。

用法：
    python scripts/compare_retrieval_modes.py --split all
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULTS_ROOT = REPO / "evals" / "results"
MODES = ["dense_only", "sparse_only", "hybrid"]


def run_mode(split: str, mode: str) -> dict:
    out_path = RESULTS_ROOT / f"_mode-{mode}-{split}.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_retrieval_eval.py"),
            "--split",
            split,
            "--mode",
            mode,
            "--out",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(REPO),
    )
    if not out_path.exists():
        return {
            "error": "eval_failed",
            "stdout": completed.stdout[-500:],
            "stderr": completed.stderr[-500:],
        }
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    out_path.unlink(missing_ok=True)
    report = payload["reports"][0]
    misses = [
        item["case_id"]
        for item in report["outcomes"]
        if item["answerable"] and not item["hit_at_5"]
    ]
    return {
        "mode": mode,
        "split": split,
        "hit_at_5_numerator": report["hit_at_5_numerator"],
        "hit_at_5_denominator": report["hit_at_5_denominator"],
        "hit_at_5": report["hit_at_5"],
        "filter_violations": report["filter_violations"],
        "negative_cases_with_evidence": report["negative_cases_with_evidence"],
        "latency_p50_seconds": report["retrieval_latency_p50_seconds"],
        "latency_p95_seconds": report["retrieval_latency_p95_seconds"],
        "missed_case_ids": misses,
        "chunk_size": report["chunk_size"],
        "chunk_overlap": report["chunk_overlap"],
        "embedding_model_id": report["embedding_model_id"],
        "snapshot_id": report.get("snapshot_id"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="all", choices=["calibration", "holdout", "all"])
    args = parser.parse_args()

    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    splits = ["calibration", "holdout"] if args.split == "all" else [args.split]

    runs: list[dict] = []
    for split in splits:
        for mode in MODES:
            result = run_mode(split, mode)
            runs.append(result)
            if result.get("error"):
                print(f"[{split}/{mode}] 失败：{result}")
                continue
            print(
                f"[{split}/{mode}] Hit@5 = {result['hit_at_5_numerator']}/"
                f"{result['hit_at_5_denominator']} = {result['hit_at_5']}  "
                f"越界={result['filter_violations']}  p50={result['latency_p50_seconds']}s"
                + (f"  未命中={result['missed_case_ids']}" if result["missed_case_ids"] else "")
            )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_ROOT / f"retrieval-mode-comparison-{stamp}.json"
    out_path.write_text(
        json.dumps(
            {
                "note": (
                    "对照实验基于虚构夹具；同一问题集、同一标注、同一快照与编码模型。"
                    "单路模式不做 RRF 融合。结论只适用于本 Demo。"
                ),
                "modes": MODES,
                "runs": runs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n对照报告：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
