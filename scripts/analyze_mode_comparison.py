"""模式对照裁决：判断混合检索相对单路是否真的更好。

判定口径（避免自欺）：
- 「无回归」的正确条件是：**hybrid 的漏检集合 ⊆ 两条单路漏检集合的交集**。
  即 hybrid 只在「两条单路都失败」的用例上失败。
- 若 hybrid 漏掉了某个「至少一条单路命中」的用例，就是真实回归，
  必须报出来而不是只看总数相同就宣称等价。

用法：python scripts/analyze_mode_comparison.py
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "evals" / "results"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=None, help="指定对照报告；缺省取最新一份")
    args = parser.parse_args()

    if args.report:
        path = Path(args.report)
    else:
        found = sorted(glob.glob(str(RESULTS / "retrieval-mode-comparison-*.json")))
        if not found:
            print("未找到模式对照报告，请先运行 compare_retrieval_modes.py")
            return 2
        path = Path(found[-1])

    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"报告：{path.name}\n")

    verdict: dict[str, object] = {"report": path.name, "splits": {}}
    for split in ("calibration", "holdout"):
        runs = {item["mode"]: item for item in data["runs"] if item["split"] == split}
        if len(runs) < 3:
            continue
        dense = set(runs["dense_only"]["missed_case_ids"])
        sparse = set(runs["sparse_only"]["missed_case_ids"])
        hybrid = set(runs["hybrid"]["missed_case_ids"])
        both_fail = dense & sparse
        regressions = sorted(hybrid - both_fail)
        recovered = sorted((dense | sparse) - hybrid)

        print(f"[{split}]")
        print(f"  Hit@5  dense_only={runs['dense_only']['hit_at_5_numerator']}"
              f"/{runs['dense_only']['hit_at_5_denominator']}"
              f"  sparse_only={runs['sparse_only']['hit_at_5_numerator']}"
              f"/{runs['sparse_only']['hit_at_5_denominator']}"
              f"  hybrid={runs['hybrid']['hit_at_5_numerator']}"
              f"/{runs['hybrid']['hit_at_5_denominator']}")
        print(f"  dense_only 漏检   : {sorted(dense) or '无'}")
        print(f"  sparse_only 漏检  : {sorted(sparse) or '无'}")
        print(f"  hybrid 漏检       : {sorted(hybrid) or '无'}")
        print(f"  hybrid 找回单路漏检: {recovered or '无'}")
        print(f"  hybrid 相对单路的回归: {regressions or '无'}")
        print(f"  时延 p50          : dense={runs['dense_only']['latency_p50_seconds']}s "
              f"sparse={runs['sparse_only']['latency_p50_seconds']}s "
              f"hybrid={runs['hybrid']['latency_p50_seconds']}s")
        print(f"  结论              : "
              f"{'无回归' if not regressions else '存在回归（见上）'}\n")

        verdict["splits"][split] = {
            "dense_only_missed": sorted(dense),
            "sparse_only_missed": sorted(sparse),
            "hybrid_missed": sorted(hybrid),
            "hybrid_recovered": recovered,
            "hybrid_regressions": regressions,
            "no_regression": not regressions,
            "hit_at_5": {
                "dense_only": runs["dense_only"]["hit_at_5"],
                "sparse_only": runs["sparse_only"]["hit_at_5"],
                "hybrid": runs["hybrid"]["hit_at_5"],
            },
        }

    out_path = RESULTS / f"retrieval-mode-verdict-{path.stem.split('-')[-1]}.json"
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"裁决记录：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
