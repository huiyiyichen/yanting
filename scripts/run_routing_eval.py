"""复杂意图路由评测（PRD AC-05）与受限字段合法率（PRD AC-04）。

**为什么在进程内跑而不是打 HTTP**：AC-05 要核对的是「理解 → 分流」这两个环节
产出的**主意图与路由**。路由结论保存在 `AgentDecision` 与审计明细里，**没有对外
接口**（客户响应刻意不暴露内部判断）。为了不为了评测而新增接口，这里直接调用与
线上同一条代码路径：`UnderstandingAnalyzer.analyze()`（真实模型）→ `decide_route()`。

**口径**：
- AC-05：20 个混合诉求案例，逐题比对主意图、路由与「次要诉求不丢失」。
- AC-04：对同一批**真实模型输出**校验受限字段是否都在枚举内（意图、情绪、投诉
  风险、故障类型/部位、渠道），样本天然来自真实输出而不是构造值。

用法（在 `code` 根目录即可）：
    .\services\api\.venv\Scripts\python.exe scripts\run_routing_eval.py
    ... --mock     # 仅用于链路自检，结果不得当作 live 结论

输出：`code/evals/results/routing-mixed-intent-<UTC>.json`
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICES_API = REPO_ROOT / "services" / "api"
if str(SERVICES_API) not in sys.path:
    sys.path.insert(0, str(SERVICES_API))

CASES_PATH = REPO_ROOT / "evals" / "cases" / "routing_mixed_intent.json"
RESULTS_DIR = REPO_ROOT / "evals" / "results"

HIGH_RISK_INTENTS = {"refund", "replacement", "repair", "parts"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="用 mock 模型自检链路（结论不作为 live 依据）")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    from app.config import get_settings
    from app.domain.agent.contracts import CaseFacts
    from app.domain.agent.routing import decide_route
    from app.domain.agent.understanding import UnderstandingAnalyzer
    from app.domain.enums import (
        ComplaintRisk,
        CustomerIntent,
        EmotionLevel,
        FaultPart,
        FaultType,
        KnowledgeHitStatus,
        PurchaseChannel,
    )

    allowed = {
        "intents": {item.value for item in CustomerIntent},
        "emotion_level": {item.value for item in EmotionLevel},
        "complaint_risk": {item.value for item in ComplaintRisk},
        "fault_type": {item.value for item in FaultType},
        "fault_part": {item.value for item in FaultPart},
        "purchase_channel": {item.value for item in PurchaseChannel},
    }

    settings = get_settings()
    if args.mock:
        from app.integrations.model_provider import MockModelProvider

        provider = MockModelProvider()
        run_mode = "mock"
    else:
        from app.integrations.model_provider import OpenAICompatibleModelProvider

        provider = OpenAICompatibleModelProvider.from_settings(settings)
        run_mode = settings.run_mode
        if not provider.available:
            print("文本模型未配置，无法执行 live 评测；如需链路自检请加 --mock")
            return 2

    analyzer = UnderstandingAnalyzer(provider)
    model_id = getattr(provider, "model_id", "") or ""

    # 与编排器同序：理解 → 订单查询（补齐渠道/地区/卖家）→ 分流。
    # 跳过订单查询会让 `purchase_channel` 恒为空，`needs_dealer_check` 误判，
    # 路由结论与线上不一致（实测会把官网订单也送进渠道核验）。
    from app.runtime import build_runtime
    from app.domain.enums import ToolName

    runtime = build_runtime(settings)
    session = runtime.new_session()
    gateway = runtime.build_gateway(session)

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    if args.limit:
        cases = cases[: args.limit]

    outcomes: list[dict[str, object]] = []
    field_checks: list[dict[str, object]] = []

    print(f"[routing] 模式={run_mode} 模型={model_id} 样本={len(cases)}")
    try:
        for index, case in enumerate(cases, start=1):
            try:
                understanding = analyzer.analyze(message=str(case["message"]))
            except Exception as exc:  # noqa: BLE001
                outcomes.append(
                    {
                        "case_id": case["case_id"],
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(f"  [{index:02d}] ERROR {case['case_id']} {type(exc).__name__}")
                continue

            intents = [item.value for item in understanding.intents]
            facts = CaseFacts(
                product_model=(
                    understanding.facts.product_model or understanding.product_model_text or None
                ),
                country_code=(
                    understanding.facts.country_code or understanding.country_code_text or None
                ),
                purchase_channel=understanding.facts.purchase_channel,
                seller_name_raw=understanding.facts.seller_name_raw,
                order_id=understanding.facts.order_id,
                fault_type=understanding.facts.fault_type,
                fault_part=understanding.facts.fault_part,
            )

            # 订单事实优先于用户叙述：只有一处订单时用它补渠道/地区/卖家
            order_result = gateway.invoke(
                ToolName.ORDER_LOOKUP, {"customerId": "CUST-DEMO-01"}
            )
            orders = order_result.data.get("orders") or [] if order_result.ok else []
            order_applied = len(orders) == 1
            if order_applied:
                single = orders[0]
                facts.order_id = single.get("orderId")
                facts.country_code = facts.country_code or single.get("countryCode")
                facts.purchase_channel = facts.purchase_channel or single.get("purchaseChannel")
                facts.seller_name_raw = facts.seller_name_raw or single.get("sellerNameRaw")

            # 3b) 消歧：同名多产品时不得直接进入高风险办理（AC-03）
            if facts.product_model:
                product_result = gateway.invoke(
                    ToolName.PRODUCT_LOOKUP, {"productModel": facts.product_model}
                )
                if product_result.ok and len(product_result.data.get("candidates") or []) == 1:
                    only = (product_result.data.get("candidates") or [])[0]
                    facts.product_id = only.get("productId")

            route = decide_route(
                facts=facts,
                intents=list(understanding.intents),
                emotion=understanding.emotion_level,
                complaint_risk=understanding.complaint_risk,
                knowledge_hit_status=KnowledgeHitStatus.SUFFICIENT,
            )

            expected_primary = case.get("expected_primary_intent")
            if expected_primary is None:
                primary_ok = not (set(intents) & HIGH_RISK_INTENTS)
            else:
                primary_ok = expected_primary in intents

            route_ok = route.route == case["expected_route"]
            kept = set(case.get("must_keep_intents") or [])
            keep_ok = kept.issubset(set(intents))

            def _enum_value(value: object) -> str:
                """枚举取 `.value`；未识别的可空字段（如渠道）按 unknown 记。"""

                raw = getattr(value, "value", value)
                return str(raw) if raw is not None else "unknown"

            outcomes.append(
                {
                    "case_id": case["case_id"],
                    "message": case["message"],
                    "ok": primary_ok and route_ok and keep_ok,
                    "expected_primary_intent": expected_primary,
                    "actual_intents": intents,
                    "primary_intent_ok": primary_ok,
                    "expected_route": case["expected_route"],
                    "actual_route": route.route,
                    "route_ok": route_ok,
                    "must_keep": sorted(kept),
                    "kept_ok": keep_ok,
                    "emotion_level": understanding.emotion_level.value,
                    "complaint_risk": understanding.complaint_risk.value,
                    "fault_type": understanding.facts.fault_type.value,
                    "fault_part": understanding.facts.fault_part.value,
                    "purchase_channel": _enum_value(understanding.facts.purchase_channel),
                    "order_applied": order_applied,
                    "is_mock": understanding.is_mock,
                }
            )

            for field, value in (
                ("intents", intents),
                ("emotion_level", understanding.emotion_level.value),
                ("complaint_risk", understanding.complaint_risk.value),
                ("fault_type", understanding.facts.fault_type.value),
                ("fault_part", understanding.facts.fault_part.value),
                ("purchase_channel", _enum_value(understanding.facts.purchase_channel)),
            ):
                values = value if isinstance(value, list) else [value]
                for item in values:
                    field_checks.append(
                        {
                            "case_id": case["case_id"],
                            "field": field,
                            "value": item,
                            "legal": item in allowed[field],
                        }
                    )

            mark = "OK " if outcomes[-1]["ok"] else "FAIL"
            print(
                f"  [{index:02d}] {mark} route={route.route:20} "
                f"intents={','.join(intents) or '-'} ch={_enum_value(facts.purchase_channel)} "
                f"{case['case_id']}"
            )
    finally:
        session.close()
        runtime.close()

    completed = [item for item in outcomes if "actual_route" in item]

    def rate(items: list[dict[str, object]], key: str) -> dict[str, object]:
        total = len(items)
        good = sum(1 for item in items if item.get(key))
        return {"total": total, "correct": good, "rate": round(good / total, 4) if total else None}

    illegal = [item for item in field_checks if not item["legal"]]
    summary = {
        "cases": len(cases),
        "completed": len(completed),
        "primary_intent": rate(completed, "primary_intent_ok"),
        "route": rate(completed, "route_ok"),
        "must_keep_intents": rate(completed, "kept_ok"),
        "all_three": rate(completed, "ok"),
        "target_rate": 0.9,
    }
    # PRD AC-05 的验收面是「主意图**和**路由」，因此达标判定取这两项；
    # 「次要诉求不丢失」是 PRD 的另一条要求，如实单列，不并入达标判定、
    # 也不因为它偏低就把已达标的项写成未达标。
    summary["meets_target"] = (
        len(completed) > 0
        and (summary["primary_intent"]["rate"] or 0) >= 0.9
        and (summary["route"]["rate"] or 0) >= 0.9
    )
    summary["secondary_intent_gap"] = summary["must_keep_intents"]["total"] - (
        summary["must_keep_intents"]["correct"]
    )
    enum_summary = {
        "checks": len(field_checks),
        "legal": len(field_checks) - len(illegal),
        "rate": (
            round((len(field_checks) - len(illegal)) / len(field_checks), 4)
            if field_checks
            else None
        ),
        "illegal": illegal[:20],
        "meets_target": bool(field_checks) and not illegal,
    }

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "note": "本报告基于虚构夹具；不得作为官方业务结论或线上指标。",
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "config": {
            "run_mode": run_mode,
            "model_id": model_id,
            "cases_file": str(CASES_PATH.relative_to(REPO_ROOT)),
            "note": "进程内调用真实理解模块 + 分流规则，不经 HTTP（路由无对外接口）",
        },
        "ac05_routing": summary,
        "ac04_enum_legality": enum_summary,
        "outcomes": outcomes,
        "field_checks": field_checks,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"routing-mixed-intent-{stamp}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== AC-05 主意图与路由 =====")
    for key in ("primary_intent", "route", "must_keep_intents", "all_three"):
        stats = summary[key]
        print(f"{key:20} {stats['correct']}/{stats['total']} = {stats['rate']}")
    print(
        f"AC-05 验收面（主意图 + 路由）目标 >= {summary['target_rate']} → "
        f"{'达标' if summary['meets_target'] else '未达标'}"
    )
    if summary["secondary_intent_gap"]:
        print(f"已知不足：{summary['secondary_intent_gap']} 题的次要诉求未被识别（单列，不并入验收面）")

    print("\n===== AC-04 受限字段合法率 =====")
    print(f"合法 {enum_summary['legal']}/{enum_summary['checks']} = {enum_summary['rate']}")
    for item in illegal[:5]:
        print(f"  非法：{item}")
    print(f"→ {'达标' if enum_summary['meets_target'] else '未达标'}")
    print(f"\n报告：{out.relative_to(REPO_ROOT)}")

    if run_mode == "mock":
        print("\n注意：本次为 mock 链路自检，结论**不得**作为 live 依据。")
        return 0
    return 0 if (summary["meets_target"] and enum_summary["meets_target"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
