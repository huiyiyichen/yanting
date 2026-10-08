"""切片参数对照实验（工程规范第 12.5 节）。

要求：优先比较 `400/60`、`600/80`、`800/100` 三种切片组合与 dense-only / 混合检索，
保留同一输入、正确证据标签、召回结果、模型/索引版本和时延。

实现说明：三种组合各自在**独立子进程**中构建暂存快照（不激活），
再按快照分别评测。独立进程是必要的：同一进程内重复导入会命中
「相同来源+版本+哈希」的幂等短路，第二个配置会复用第一个配置的片段，
导致三种配置得到完全相同的索引（这是实际踩到过的坑）。

用法：
    python scripts/compare_chunk_configs.py --split calibration
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "data" / "knowledge" / "manifest.json"
RESULTS_ROOT = REPO / "evals" / "results"
COMBOS = [(400, 60), (600, 80), (800, 100)]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(REPO),
    )


def build_snapshot(chunk_size: int, chunk_overlap: int) -> dict:
    """在独立子进程中构建暂存快照，返回其报告。"""

    out_path = RESULTS_ROOT / f"_ingest-{chunk_size}-{chunk_overlap}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    completed = _run(
        [
            sys.executable,
            str(REPO / "scripts" / "ingest_knowledge.py"),
            "--no-activate",
            "--json",
            "--out",
            str(out_path),
            "--chunk-size",
            str(chunk_size),
            "--chunk-overlap",
            str(chunk_overlap),
        ]
    )
    if not out_path.exists():
        return {
            "error": "ingest_failed",
            "stdout": completed.stdout[-500:],
            "stderr": completed.stderr[-500:],
        }
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    out_path.unlink(missing_ok=True)
    return payload


def run_eval(split: str, snapshot_id: str, chunk_size: int, chunk_overlap: int) -> dict:
    out_path = RESULTS_ROOT / f"_eval-{chunk_size}-{chunk_overlap}-{split}.json"
    completed = _run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_retrieval_eval.py"),
            "--split",
            split,
            "--snapshot",
            snapshot_id,
            "--chunk-size",
            str(chunk_size),
            "--chunk-overlap",
            str(chunk_overlap),
            "--out",
            str(out_path),
        ]
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
    return {
        "hit_at_5_numerator": report["hit_at_5_numerator"],
        "hit_at_5_denominator": report["hit_at_5_denominator"],
        "hit_at_5": report["hit_at_5"],
        "filter_violations": report["filter_violations"],
        "negative_cases_with_evidence": report["negative_cases_with_evidence"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", default="calibration")
    args = parser.parse_args()

    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for chunk_size, chunk_overlap in COMBOS:
        print(f"--- chunk={chunk_size}/{chunk_overlap} ---")
        built = build_snapshot(chunk_size, chunk_overlap)
        if built.get("error"):
            print(f"    构建失败：{built}")
            rows.append({"chunk_size": chunk_size, "chunk_overlap": chunk_overlap, **built})
            continue
        print(
            f"    snapshot={built['snapshot_id']} chunks={built['chunks_created']} "
            f"max={built['max_chunk_chars']} mean={built['mean_chunk_chars']} "
            f"({built.get('ingest_seconds', '')})"
        )
        evaluated = run_eval(
            args.split, str(built["snapshot_id"]), chunk_size, chunk_overlap
        )
        row = {**built, "eval": evaluated}
        rows.append(row)
        print(
            f"    Hit@5 = {evaluated.get('hit_at_5_numerator')}/"
            f"{evaluated.get('hit_at_5_denominator')} = {evaluated.get('hit_at_5')}"
            f"  越界={evaluated.get('filter_violations')}"
        )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_ROOT / f"chunk-comparison-{args.split}-{stamp}.json"
    out_path.write_text(
        json.dumps(
            {
                "note": (
                    "对照实验基于虚构夹具；快照为 staging 状态，未激活。"
                    "结论只适用于本 Demo，不声称线上最优。"
                ),
                "split": args.split,
                "combos": [f"{size}/{overlap}" for size, overlap in COMBOS],
                "fusion": "qdrant_rrf(dense + sparse)",
                "runs": rows,
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
