"""产品型号消歧评测（PRD AC-02 / AC-03）。

**口径**：AC-02 要求「在带标准答案的 20 个案例中统计唯一正确型号」。
本脚本用标注集 `evals/cases/model_disambiguation.json` 逐题执行**真实候选召回**
（`match_products_by_name` + `products_by_model`），统计：

- `resolvable` 题：top-1 候选必须落在标注的型号上（正确 = 命中的是唯一正确型号）；
- `ambiguous` 题：必须**召回 ≥2 个同名候选**并判定为「需确认」，不得直接选定某一款；
- `unresolvable` 题：不得强行给出型号（禁止把噪音当结论，对应 AC-10）。

三类合起来就是「唯一正确型号」的判定：能给唯一答案的给对、该问的问、不知道的不编。
纯离线、确定性，不需要模型调用；因此可重复运行且结果稳定。

用法（在 `code/services/api` 下）：
    .\.venv\Scripts\python.exe ..\..\scripts\run_model_disambiguation_eval.py

输出：`code/evals/results/model-disambiguation-<UTC>.json`
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# 脚本位于 <code>/scripts，包在 <code>/services/api/app：显式加入搜索路径，
# 这样从任何工作目录运行都能 import app.*（不依赖 cwd）。
SERVICES_API = REPO_ROOT / "services" / "api"
if str(SERVICES_API) not in sys.path:
    sys.path.insert(0, str(SERVICES_API))

CASES_PATH = REPO_ROOT / "evals" / "cases" / "model_disambiguation.json"
RESULTS_DIR = REPO_ROOT / "evals" / "results"


def _evaluate_case(case: dict[str, object], top_k: int) -> dict[str, object]:
    from app.domain.after_sales.fixtures import match_products_by_name, products_by_model

    query = str(case["query"])
    expected_model = case.get("expected_model")
    expected_product_id = case.get("expected_product_id")
    kind = str(case["kind"])

    recalled = match_products_by_name(query, limit=top_k)
    top_model = recalled[0][0].product_model if recalled else None

    # 同一型号下的候选项数量：>1 说明型号本身不足以定位到唯一产品
    same_model = products_by_model(top_model) if top_model else []
    is_ambiguous = len(same_model) > 1

    if kind == "resolvable":
        top_product_id = recalled[0][0].product_id if recalled else None
        # 唯一正确型号：必须有召回、型号匹配，且能定位到标注的具体产品
        correct = (
            top_model is not None
            and top_model == expected_model
            and (expected_product_id is None or top_product_id == expected_product_id)
        )
        note = f"top1={top_model}/{top_product_id}"
    elif kind == "ambiguous":
        # 必须识别出型号，同时**判定为多候选需确认**，不得直接选定
        correct = top_model is not None and top_model == expected_model and is_ambiguous
        note = f"top1={top_model} 同型号候选={len(same_model)} 需确认={is_ambiguous}"
    else:  # unresolvable
        # 没有可识别型号：不得编造具体型号
        correct = top_model is None
        note = f"top1={top_model}"

    return {
        "case_id": case["case_id"],
        "query": query,
        "kind": kind,
        "expected_model": expected_model,
        "expected_product_id": expected_product_id,
        "top1_model": top_model,
        "top1_product_id": recalled[0][0].product_id if recalled else None,
        "recall_count": len(recalled),
        "same_model_candidate_count": len(same_model),
        "needs_confirmation": is_ambiguous,
        "correct": correct,
        "note": note,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]

    outcomes = [_evaluate_case(case, args.top_k) for case in cases]

    def _rate(items: list[dict[str, object]]) -> dict[str, object]:
        total = len(items)
        correct = sum(1 for item in items if item["correct"])
        return {
            "total": total,
            "correct": correct,
            "rate": round(correct / total, 4) if total else None,
        }

    by_kind = {
        kind: _rate([item for item in outcomes if item["kind"] == kind])
        for kind in ("resolvable", "ambiguous", "unresolvable")
    }
    overall = _rate(outcomes)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "note": "本报告基于虚构夹具；不得作为官方业务结论或线上指标。",
        "metric": "AC-02 产品型号消歧准确率（唯一正确型号 / 标注案例数）",
        "method": "确定性候选召回：match_products_by_name + products_by_model，无模型调用",
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "config": {"top_k": args.top_k, "cases_file": str(CASES_PATH.relative_to(REPO_ROOT))},
        "overall": overall,
        "by_kind": by_kind,
        "target_rate": 0.9,
        "meets_target": (overall["rate"] or 0) >= 0.9,
        "outcomes": outcomes,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else RESULTS_DIR / f"model-disambiguation-{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'case':7} {'kind':13} {'top1':9} {'候选':4} {'同型号':6} 结果")
    for item in outcomes:
        mark = "OK  " if item["correct"] else "FAIL"
        top1 = item["top1_model"] or "-"
        print(
            f"{item['case_id']:7} {item['kind']:13} {top1:9} "
            f"{item['recall_count']:<4} {item['same_model_candidate_count']:<6} {mark} {item['note']}"
        )

    print("\n===== 汇总 =====")
    for kind, stats in by_kind.items():
        print(f"{kind:13} {stats['correct']}/{stats['total']} = {stats['rate']}")
    print(f"{'整体':13} {overall['correct']}/{overall['total']} = {overall['rate']}")
    print(f"目标 >= {report['target_rate']} → {'达标' if report['meets_target'] else '未达标'}")
    print(f"报告：{out.relative_to(REPO_ROOT)}")
    return 0 if report["meets_target"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
