"""Agent 节点的输入/输出摘要（反馈 10-18 #3a）。

过去只有模型调用跨度带 input/output 产物，Agent 节点本身为空，检查器显示「无」。
这里把每个编排节点读到的关键输入与写回的关键输出压缩成可读 JSON，并给出一句话产出摘要。
摘要只读状态，不改状态；任何异常都返回空，记录永远不打断业务。
"""

from __future__ import annotations

from typing import Any

_MAX_TEXT = 240
_MAX_ITEMS = 8


def _brief(value: Any, depth: int = 0) -> Any:
    if depth > 3:
        return "…"
    if hasattr(value, "model_dump"):
        try:
            value = value.model_dump(mode="json", by_alias=True)
        except Exception:  # pragma: no cover - defensive
            value = str(value)
    if isinstance(value, str):
        return value if len(value) <= _MAX_TEXT else value[:_MAX_TEXT] + "…"
    if isinstance(value, dict):
        return {str(k): _brief(v, depth + 1) for k, v in list(value.items())[:16]}
    if isinstance(value, (list, tuple, set)):
        items = [_brief(v, depth + 1) for v in list(value)[:_MAX_ITEMS]]
        if len(value) > _MAX_ITEMS:
            items.append(f"…共 {len(value)} 项")
        return items
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_TEXT]


def _source_kinds(sources: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for source in sources or []:
        kind = getattr(source, "kind", "other")
        out[kind] = out.get(kind, 0) + 1
    return out


VERIFY_REASON_TEXT = {
    "cited": "引用了资料", "number": "含数字", "status": "含订单/物流状态", "efficacy": "含功效说法",
    "product": "含商品结论", "advice": "有个性化建议", "breakpoints": "有服务断点", "images": "有图片",
    "high_risk": "高风险会话", "safety_intent": "安全类问题", "policy_disabled": "按需核验未开启",
}


def verify_reason_text(reasons: list[Any]) -> list[str]:
    return [VERIFY_REASON_TEXT.get(str(r), str(r)) for r in reasons or []]


def _replies(draft: Any) -> list[dict[str, Any]]:
    return [{"style": getattr(r, "style", ""), "body": getattr(r, "body", "")}
            for r in getattr(draft, "reply_suggestions", []) or []]


def describe(agent: str, state: dict[str, Any], result: dict[str, Any]) -> tuple[Any, Any, str]:
    """返回 (输入摘要, 输出摘要, 一句话产出)。"""
    try:
        return _describe(agent, state or {}, result or {})
    except Exception:  # pragma: no cover - recording never breaks the flow
        return None, None, ""


def _describe(agent: str, state: dict[str, Any], result: dict[str, Any]) -> tuple[Any, Any, str]:
    latest = state.get("latest_message") or result.get("latest_message") or ""
    issues = [str(i)[:200] for i in result.get("issues", []) or []]
    if agent == "trajectory":
        context = result.get("context")
        products = [p.name for p in getattr(context, "products", [])[:4]]
        orders = [o.order_id for o in getattr(context, "orders", [])[:4]]
        sources = result.get("sources") or []
        output = {"最新消息": latest, "商品": products, "订单": orders,
                  "服务来源": _source_kinds(sources), "图片": len(result.get("images") or []),
                  "风险等级": result.get("risk_level")}
        head = f"读取 {len(sources)} 条服务来源"
        return _brief({"最新客户消息": latest, "消息数": len(result.get("messages") or [])}), _brief(output), (
            head + (f" · {products[0]}" if products else "") + (f" · {len(orders)} 个订单" if orders else ""))
    if agent == "knowledge":
        hits = result.get("knowledge") or []
        titles = list(dict.fromkeys(str(h.get("document_title", "")) for h in hits if h.get("document_title")))
        output = {"命中状态": result.get("knowledge_status"), "命中": [
            {"资料": h.get("document_title"), "摘录": h.get("quoted_excerpt")} for h in hits[:6]]}
        summary = f"命中 {len(hits)} 条知识：{'、'.join(titles[:2])}" if hits else "未命中相关知识"
        products = [p.name for p in getattr(state.get("context"), "products", [])[:2]]
        return _brief({"检索问题": latest, "商品": products}), _brief(output), summary
    if agent == "vision":
        images = result.get("images") or []
        observed = [_brief(getattr(i, "observation", None)) for i in images]
        return {"图片数": len(state.get("images") or [])}, _brief({"观察": observed}), f"读取 {len(images)} 张图片"
    if agent == "composer":
        draft = result.get("draft")
        replies = _replies(draft)
        chars = len(replies[0]["body"]) if replies else 0
        output = {"意图": getattr(draft, "intent", None), "当前问题": getattr(draft, "current_question", ""),
                  "回复": replies, "转人工": getattr(draft, "handoff_required", None)}
        summary = (f"草稿 {chars} 字" + (f" · 共 {len(replies)} 版" if len(replies) > 1 else "")) if replies \
            else "未产出可用草稿"
        if result.get("attempt", 1) and result.get("attempt", 1) > 1:
            summary += f" · 第 {result['attempt']} 次起草"
        return (_brief({"最新消息": latest, "来源数": len(state.get("sources") or []),
                        "知识命中": len(state.get("knowledge") or []), "修复要求": state.get("issues") or []}),
                _brief(output), summary)
    if agent in {"program_check", "verifier"}:
        draft = state.get("draft")
        why = verify_reason_text(result.get("verify_reasons") or state.get("verify_reasons") or [])
        if agent == "program_check":
            checks = result.get("check_items") or []
            failed = [c for c in checks if c.get("hit")]
            output = {"检查项": [{"项目": c["name"], "结果": ("✗ " if c.get("hit") else "✓ ") + c["detail"]} for c in checks],
                      "问题": issues, "需事实核验的原因": why}
            summary = (f"{len(checks)} 项检查全部通过" if not failed else f"{len(failed)} 项未通过：{failed[0]['name']}") \
                if checks else ("程序核验通过" if not issues else f"发现 {len(issues)} 个问题：{issues[0][:40]}")
            if not issues and why:
                summary += f" · {'、'.join(why[:2])}，交事实核验"
            return _brief({"回复": _replies(draft)}), _brief(output), summary
        output = {"问题": issues, "核验原因": why}
        summary = (f"逐条对照来源，{'、'.join(why[:2])}均有据" if why else "事实核验通过") if not issues \
            else f"发现 {len(issues)} 个问题：{issues[0][:40]}"
        return _brief({"回复": _replies(draft)}), _brief(output), summary
    if agent == "output_gate":
        draft = result.get("draft") or state.get("draft")
        replies = _replies(draft)
        dropped = result.get("segments_dropped") or 0
        flags = result.get("review_flags") or []
        chars = len(replies[0]["body"]) if replies else 0
        summary = (f"定稿 {chars} 字" if replies else "没有可发送的回复") + (f" · 删去 {dropped} 段" if dropped else "") \
            + (f" · {len(flags)} 处待复核" if flags else "")
        return None, _brief({"最终回复": replies, "待复核": flags, "删去段数": dropped}), summary
    keys = sorted(k for k in result if k not in {"steps", "calls"})
    return None, _brief({k: result[k] for k in keys[:8]}), ""
