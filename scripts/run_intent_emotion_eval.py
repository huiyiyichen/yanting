"""意图与情绪评测：规则基线 vs 意图与情绪 Agent（规则优先 + 快速档模型）。

用法（仓库根）：
  services/api/.venv/bin/python scripts/run_intent_emotion_eval.py            # 只跑规则基线（离线）
  services/api/.venv/bin/python scripts/run_intent_emotion_eval.py --live     # 再跑 Agent，读 .env 的模型配置
报告写到 data/runtime/evals/intent_emotion_<时间>.json，并在终端打印对比表。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services/api"))

from app.evaluation.understanding_eval import load_cases, run  # noqa: E402

CASES = REPO / "evals" / "cases" / "loreal_intent_emotion.json"


def _live_model(usage: list[dict]):
    from app.config import get_settings
    from app.integrations.model_provider import ChatMessage, OpenAICompatibleModelProvider

    settings = get_settings()
    provider = OpenAICompatibleModelProvider.from_settings(settings)
    if not provider.available():
        raise SystemExit("模型未配置：请在 .env 设置 YANTING_LLM_BASE_URL / YANTING_LLM_MODEL / API Key")

    def ask(system: str, payload: dict) -> str:
        result = provider.complete(
            [ChatMessage(role="system", content=system),
             ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False))],
            temperature=0, max_tokens=200, json_mode=True, model_tier="fast",
        )
        usage.append({"model": result.model, "promptTokens": result.prompt_tokens,
                      "completionTokens": result.completion_tokens, "cachedTokens": result.cached_tokens})
        return result.text
    return ask, provider


def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def table(reports: dict[str, dict]) -> str:
    rows = [
        ("意图 准确率", lambda m: _pct(m["intent"]["accuracy"])),
        ("意图 macro-F1", lambda m: _pct(m["intent"]["macroF1"])),
        ("情绪 准确率", lambda m: _pct(m["emotion"]["accuracy"])),
        ("情绪 macro-F1", lambda m: _pct(m["emotion"]["macroF1"])),
        ("负面情绪召回", lambda m: _pct(m["emotion"]["negativeRecall"])),
        ("愤怒召回", lambda m: _pct(m["emotion"]["angryRecall"])),
        ("平稳误报率", lambda m: _pct(m["emotion"]["calmFalseAlarmRate"])),
        ("拿不准比例（交给模型）", lambda m: _pct(m["cost"]["uncertainRate"])),
        ("实际调用模型比例", lambda m: _pct(m["cost"]["modelCallRate"])),
        ("规则错误被分流召回", lambda m: _pct(m["cost"]["errorRoutingRecall"])),
        ("每条 Token", lambda m: f"{m['cost']['tokensPerMessage']:.0f}"),
    ]
    tags = sorted({tag for r in reports.values() for tag in r["metrics"]["byTag"]})
    for tag in tags:
        rows.append((f"[{tag}] 意图/情绪", lambda m, t=tag: (
            f"{_pct(m['byTag'][t]['intentAccuracy'])} / {_pct(m['byTag'][t]['emotionAccuracy'])}"
            if t in m["byTag"] else "—")))
    names = list(reports)
    lines = ["| 指标 | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for label, fn in rows:
        lines.append(f"| {label} | " + " | ".join(fn(reports[n]["metrics"]) for n in names) + " |")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="同时评测意图与情绪 Agent（会调用真实模型）")
    args = parser.parse_args()
    cases = load_cases(CASES)
    reports = {"规则基线": run(cases, None)}
    meta: dict = {}
    if args.live:
        usage: list[dict] = []
        ask, provider = _live_model(usage)
        reports["意图情绪 Agent"] = run(cases, ask, usage)
        meta = {"model": provider.fast_model_id}
    out = REPO / "data" / "runtime" / "evals" / f"intent_emotion_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"createdAt": datetime.now(UTC).isoformat(), "cases": str(CASES.relative_to(REPO)),
                               **meta, "reports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(table(reports))
    print(f"\n报告：{out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
