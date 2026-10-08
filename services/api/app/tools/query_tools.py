"""订单、产品、经销商与质保查询工具。

查询类工具都是 `read_only`：只读夹具/数据库，不产生业务副作用，
也不修改源订单（AC-20：候选选择不改订单）。

`create_request_draft` 属于 `request_creation`：只生成待人工确认的草稿，
**不执行**真实退款、换货、维修或派单（PRD 第 1.4 节）。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.domain.after_sales import fixtures
from app.domain.enums import (
    ComplaintRisk,
    EmotionLevel,
    FaultType,
    KnowledgeHitStatus,
    PurchaseChannel,
    RatingStatus,
    RequestType,
    ToolName,
    TroubleshootingResult,
)
from app.tool_gateway.contracts import ToolContext, ToolResult


def order_lookup(
    *,
    customer_id: str | None = None,
    order_id: str | None = None,
    order_no_masked: str | None = None,
    product_id: str | None = None,
    tool_request_id: str | None = None,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
) -> ToolResult:
    """按客户/订单号查询订单。"""

    del idempotency_key, context
    if order_id:
        order = fixtures.find_order(order_id)
        orders = [order] if order else []
    elif order_no_masked:
        orders = fixtures.find_orders_by_masked_no(order_no_masked)
    elif product_id:
        orders = fixtures.find_orders_by_product(product_id)
    elif customer_id:
        orders = fixtures.find_orders_by_customer(customer_id)
    else:
        return ToolResult.error(
            ToolName.ORDER_LOOKUP,
            "invalid_argument",
            "至少需要提供 customer_id、order_id、order_no_masked 或 product_id 之一",
        )

    if not orders:
        return ToolResult(
            tool=ToolName.ORDER_LOOKUP,
            status="not_found",
            data={"orders": []},
            message="订单未命中。这不等于非授权或过保，需要补充凭证或核验渠道。",
        )

    return ToolResult(
        tool=ToolName.ORDER_LOOKUP,
        status="ok",
        data={
            "orders": [
                {
                    "orderId": item.order_id,
                    "orderNoMasked": item.order_no_masked,
                    "customerId": item.customer_id,
                    "productId": item.product_id,
                    "productModel": item.product_model,
                    "productNameSnapshot": item.product_name_snapshot,
                    "sku": item.sku,
                    "purchasedAt": item.purchased_at.isoformat(),
                    "countryCode": item.country_code,
                    "purchaseChannel": item.purchase_channel.value,
                    "sellerNameRaw": item.seller_name_raw,
                    "sellerNameStandard": item.seller_name_standard,
                    "warrantyMonths": item.warranty_months,
                    "status": item.status,
                }
                for item in orders
            ]
        },
        message=f"命中 {len(orders)} 笔订单。",
    )


def product_lookup(
    *,
    query: str | None = None,
    product_model: str | None = None,
    include_ambiguous: bool = True,
    tool_request_id: str | None = None,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
) -> ToolResult:
    """产品候选召回或同名产品的全部候选。

    AC-03：未确认的多候选产品必须阻止高风险办理。本工具只提供候选，
    是否唯一由调用方结合订单事实判断，**不擅自选定**。
    """

    if product_model:
        matches = fixtures.products_by_model(product_model)
        if not matches:
            return ToolResult(
                tool=ToolName.PRODUCT_LOOKUP,
                status="not_found",
                data={"candidates": [], "unique": False},
                message=f"产品数据库中不存在型号 {product_model}。",
            )
        return ToolResult(
            tool=ToolName.PRODUCT_LOOKUP,
            status="ok",
            data={
                "unique": len(matches) == 1 and not include_ambiguous,
                "candidateCount": len(matches),
                "requiresDisambiguation": len(matches) > 1,
                "candidates": [_product_payload(item) for item in matches],
            },
            message=(
                f"型号 {product_model} 对应 {len(matches)} 个候选，需要消歧。"
                if len(matches) > 1
                else f"型号 {product_model} 唯一匹配。"
            ),
        )

    if not query:
        return ToolResult.error(
            ToolName.PRODUCT_LOOKUP, "invalid_argument", "需要提供 query 或 product_model"
        )

    scored = fixtures.match_products_by_name(query)
    if not scored:
        return ToolResult(
            tool=ToolName.PRODUCT_LOOKUP,
            status="empty",
            data={"candidates": []},
            message="未能从描述中召回任何产品候选。",
        )
    return ToolResult(
        tool=ToolName.PRODUCT_LOOKUP,
        status="ok",
        data={
            "candidateCount": len(scored),
            "requiresDisambiguation": len(scored) > 1,
            # 分数只是候选排序信号，不是确认结果
            "candidates": [
                {**_product_payload(item), "matchScore": round(score, 2)} for item, score in scored
            ],
        },
        message=f"召回 {len(scored)} 个候选，均需用户或订单确认。",
    )


def dealer_lookup(
    *,
    seller_name_raw: str,
    country_code: str | None = None,
    purchase_channel: str | None = None,
    tool_request_id: str | None = None,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
) -> ToolResult:
    """经销商授权核验。

    严格区分 unclear / multiple / failed / not_authorized。
    不提供授权名单供用户挑选证明（AC-18）。
    """

    channel: PurchaseChannel | None = None
    if purchase_channel:
        try:
            channel = PurchaseChannel(purchase_channel)
        except ValueError:
            return ToolResult.error(
                ToolName.DEALER_LOOKUP,
                "invalid_argument",
                f"未知的购买渠道：{purchase_channel}",
            )

    try:
        match = fixtures.verify_dealer_authorization(
            seller_name_raw=seller_name_raw, country_code=country_code, channel=channel
        )
    except FileNotFoundError as exc:
        # 名录缺失属于查询失败，绝不是「非授权」
        return ToolResult.error(ToolName.DEALER_LOOKUP, "failed", str(exc))

    status_value = match.status.value
    tool_status = {
        "authorized": "ok",
        "not_authorized": "ok",
        "multiple_matches": "conflict",
        "unknown": "empty",
        "query_failed": "failed",
        "not_applicable": "empty",
    }.get(status_value, "failed")

    return ToolResult(
        tool=ToolName.DEALER_LOOKUP,
        status=tool_status,  # type: ignore[arg-type]
        data={
            "authorizationStatus": status_value,
            "sellerNameRaw": match.seller_name_raw,
            "sellerNameStandard": match.seller_name_standard,
            "bestScore": round(match.best_score, 2) if match.best_score is not None else None,
            "candidateCount": len(match.candidates),
            "candidateIds": [item.dealer_id for item in match.candidates],
            "note": match.note,
        },
        message=match.note,
    )


def warranty_evaluate(
    *,
    order_id: str,
    on_date: str | None = None,
    tool_request_id: str | None = None,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
) -> ToolResult:
    """按订单事实计算质保状态。不编造规则，只做日期算术。"""

    del idempotency_key, context
    order = fixtures.find_order(order_id)
    if order is None:
        return ToolResult(
            tool=ToolName.WARRANTY_EVALUATE,
            status="not_found",
            data={"warrantyStatus": "unknown"},
            message="订单未命中，无法判定质保；不得据此判定过保。",
        )
    parsed_date: date | None = None
    if on_date:
        try:
            parsed_date = date.fromisoformat(on_date)
        except ValueError:
            return ToolResult.error(
                ToolName.WARRANTY_EVALUATE, "invalid_argument", f"on_date 不是 ISO 日期：{on_date}"
            )
    evaluation = fixtures.evaluate_warranty(order, on_date=parsed_date)
    return ToolResult(
        tool=ToolName.WARRANTY_EVALUATE,
        status="ok",
        data={
            "warrantyStatus": evaluation.status.value,
            "reason": evaluation.reason,
            "warrantyMonths": evaluation.warranty_months,
            "expiresOn": evaluation.expires_on.isoformat() if evaluation.expires_on else None,
            "daysRemaining": evaluation.days_remaining,
            "orderId": order.order_id,
        },
        message=evaluation.reason,
    )


def _product_payload(item: fixtures.Product) -> dict[str, Any]:
    return {
        "productId": item.product_id,
        "productModel": item.product_model,
        "productCategory": item.product_category,
        "displayName": item.display_name,
        "sku": item.sku,
        "regions": list(item.regions),
        "releasedAt": item.released_at.isoformat(),
        "specHighlights": list(item.spec_highlights),
    }


def tool_context_note() -> ToolContext:
    """返回一个只读上下文，供审计记录使用。"""

    return ToolContext(read_only=True)


# --------------------------------------------------------------- 知识检索工具


def knowledge_search_tool(
    *,
    query: str,
    product_model: str | None = None,
    country_code: str | None = None,
    purchase_channel: str | None = None,
    audience: str | None = None,
    tool_request_id: str | None = None,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
    session: Any = None,
    settings: Any = None,
    embedding_provider: Any = None,
    rerank_provider: Any = None,
) -> ToolResult:
    """混合检索知识并返回带来源定位的证据。

    权限由服务端决定：默认按 `customer_visible`；
    只有客服侧上下文才允许读取 `internal`。模型传入的 `audience` 只在
    调用方显式允许时生效（由 Agent 层控制），这里再做一次兜底校验。
    """

    del idempotency_key
    from app.domain.enums import Visibility
    from app.knowledge.retrieval import RetrievalRequest, retrieve

    # 权限校验必须放在依赖检查之前：越权请求无论运行环境是否完整，
    # 都必须得到明确的「无权限」，而不是被别的错误掩盖成一次普通失败。
    resolved_audience = Visibility.CUSTOMER_VISIBLE
    if audience == Visibility.INTERNAL.value:
        ctx = context or ToolContext()
        # 只有显式标记为客服侧的上下文才允许读内部资料
        if ctx.requested_by not in {"support", "operator"}:
            return ToolResult.error(
                ToolName.KNOWLEDGE_SEARCH,
                "denied",
                "当前上下文无权读取内部知识；客户会话只能检索客户可见资料",
            )
        resolved_audience = Visibility.INTERNAL

    if session is None or settings is None or embedding_provider is None:
        return ToolResult.error(
            ToolName.KNOWLEDGE_SEARCH,
            "failed",
            "知识检索工具缺少运行时依赖（session/settings/embedding_provider）",
        )

    result = retrieve(
        session,
        settings=settings,
        embedding_provider=embedding_provider,
        rerank_provider=rerank_provider,
        request=RetrievalRequest(
            query=query,
            audience=resolved_audience,
            product_model=product_model,
            country_code=country_code,
            purchase_channel=purchase_channel,
        ),
    )
    tool_status = {
        KnowledgeHitStatus.SUFFICIENT: "ok",
        KnowledgeHitStatus.INSUFFICIENT: "empty",
        KnowledgeHitStatus.NOT_FOUND: "not_found",
        KnowledgeHitStatus.CONFLICTING: "conflict",
    }[result.hit_status]

    return ToolResult(
        tool=ToolName.KNOWLEDGE_SEARCH,
        status=tool_status,  # type: ignore[arg-type]
        data={
            "retrievalId": result.retrieval_id,
            "snapshotId": result.snapshot_id,
            "hitStatus": result.hit_status.value,
            "audience": resolved_audience.value,
            "evidence": [item.model_dump(mode="json") for item in result.evidence],
            "notes": result.notes,
            "filter": result.filter_summary,
        },
        message=f"命中 {len(result.evidence)} 条证据（{result.hit_status.value}）",
        tool_request_id=tool_request_id,
    )


def troubleshooting_plan(
    *,
    case_id: str,
    fault_type: str | None = None,
    product_model: str | None = None,
    tool_request_id: str | None = None,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
) -> ToolResult:
    """依据已检索到的 SOP 证据生成分步排障引导。

    本工具**不自行编造步骤**：它只把候选故障类型映射为需要检索的查询，
    实际步骤必须来自 `knowledge_search` 返回的证据。因此这里返回的是
    「建议检索的问题」与固定枚举，而不是凭空生成的排障内容。
    """

    del idempotency_key, case_id, context
    resolved_fault = FaultType.UNKNOWN
    if fault_type:
        try:
            resolved_fault = FaultType(fault_type)
        except ValueError:
            return ToolResult.error(
                ToolName.TROUBLESHOOTING_PLAN,
                "invalid_argument",
                f"未知故障类型：{fault_type}",
            )

    queries = [
        f"{product_model or ''} {resolved_fault.label} 排障步骤".strip(),
        f"{product_model or ''} {resolved_fault.label} 注意事项".strip(),
    ]
    return ToolResult(
        tool=ToolName.TROUBLESHOOTING_PLAN,
        status="ok",
        data={
            "faultType": resolved_fault.value,
            "suggestedQueries": queries,
            "requiresUserConfirmationToMarkResolved": True,
            "note": ("排障步骤必须来自检索到的 SOP 证据；未经用户明确确认，不得记录为已解决。"),
        },
        message="已生成排障检索计划；步骤内容须以检索证据为准",
        tool_request_id=tool_request_id,
    )


# ----------------------------------------------------------- 记录类工具


def record_case_fact(
    *,
    case_id: str,
    field_name: str,
    value: Any = None,
    tool_request_id: str | None = None,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
    session: Any = None,
) -> ToolResult:
    """写入单个案件事实。字段必须属于允许写入的白名单，非法字段拒绝。"""

    del idempotency_key, context
    if session is None:
        return ToolResult.error(
            ToolName.RECORD_CASE_FACT, "failed", "缺少数据库会话，无法写入案件事实"
        )

    from app.repositories.conversation_repository import ConversationRepository

    allowed: dict[str, tuple[str, Any]] = {
        "country_code": ("country_code", str),
        "purchase_channel": ("purchase_channel", str),
        "seller_name_raw": ("seller_name_raw", str),
        "product_model": ("product_model", str),
        "product_id": ("product_id", str),
        "product_category": ("product_category", str),
        "emotion_level": ("emotion_level", EmotionLevel),
        "complaint_risk": ("complaint_risk", ComplaintRisk),
        "troubleshooting_result": ("troubleshooting_result", TroubleshootingResult),
        "closure_reason": ("closure_reason", str),
    }
    if field_name not in allowed:
        return ToolResult.error(
            ToolName.RECORD_CASE_FACT,
            "invalid_argument",
            f"不允许写入案件字段 {field_name}；允许字段：{sorted(allowed)}",
        )

    repo = ConversationRepository(session)
    case = repo.get_case(case_id)
    if case is None:
        return ToolResult.error(ToolName.RECORD_CASE_FACT, "not_found", f"案件不存在：{case_id}")

    column, caster = allowed[field_name]
    if caster is EmotionLevel or caster is ComplaintRisk or caster is TroubleshootingResult:
        try:
            parsed = caster(value)
        except ValueError:
            return ToolResult.error(
                ToolName.RECORD_CASE_FACT,
                "invalid_argument",
                f"{field_name} 取值非法：{value}",
            )
        repo.update_case_facts(case, **{column: parsed})  # type: ignore[arg-type]
    else:
        repo.update_case_facts(case, **{column: str(value)})  # type: ignore[arg-type]

    return ToolResult(
        tool=ToolName.RECORD_CASE_FACT,
        status="ok",
        data={"caseId": case_id, "field": field_name},
        message=f"已记录案件字段 {field_name}",
        tool_request_id=tool_request_id,
    )


def record_rating(
    *,
    case_id: str,
    action: str,
    rating: int | None = None,
    tool_request_id: str | None = None,
    idempotency_key: str | None = None,
    context: ToolContext | None = None,
    session: Any = None,
) -> ToolResult:
    """发起/提交/跳过满意度。服务未结束时不允许发起（PRD 第 5.2 节）。"""

    del idempotency_key, context
    if session is None:
        return ToolResult.error(ToolName.RECORD_RATING, "failed", "缺少数据库会话")

    from app.domain.case_state.state_machine import next_rating_status, rating_allowed
    from app.domain.enums import CaseStatus
    from app.repositories.conversation_repository import ConversationRepository

    repo = ConversationRepository(session)
    case = repo.get_case(case_id)
    if case is None:
        return ToolResult.error(ToolName.RECORD_RATING, "not_found", f"案件不存在：{case_id}")

    current = RatingStatus(case.rating_status)
    if action == "request":
        open_requests = repo.list_open_requests(case_id)
        from app.domain.enums import RequestStatus

        gate = rating_allowed(
            CaseStatus(case.case_status),
            [RequestStatus(item.request_status) for item in open_requests],
        )
        if not gate.allowed:
            return ToolResult.error(ToolName.RECORD_RATING, "conflict", gate.reason)

    try:
        target = next_rating_status(current, action)
    except Exception as exc:
        return ToolResult.error(ToolName.RECORD_RATING, "invalid_argument", str(exc))

    if action == "submit" and rating is None:
        return ToolResult.error(
            ToolName.RECORD_RATING, "invalid_argument", "提交评价时必须提供 1—5 的评分"
        )

    repo.set_rating(
        case,
        status=target,
        rating=rating if action == "submit" else None,
    )
    return ToolResult(
        tool=ToolName.RECORD_RATING,
        status="ok",
        data={
            "caseId": case_id,
            "ratingStatus": target.value,
            # 跳过时评分必须为空，不得填默认分
            "userRating": case.user_rating,
        },
        message=f"评价状态更新为 {target.value}",
        tool_request_id=tool_request_id,
    )


# --------------------------------------------------------- 申请草稿工具


def create_request_draft(
    *,
    case_id: str,
    request_type: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    tool_request_id: str | None = None,
    context: ToolContext | None = None,
    session: Any = None,
) -> ToolResult:
    """生成售后申请草稿并进入待人工确认。

    严格要求（PRD 第 3.4 节 F3-02 与第 4.3 节）：
    - 生成草稿前必须已确认型号、国家/地区与质保结论；
    - 本工具**不执行**任何真实业务动作，批准也不等于真实退款完成；
    - 相同幂等键重复提交返回同一条申请，不产生重复申请。
    """

    del context
    if session is None:
        return ToolResult.error(ToolName.CREATE_AFTER_SALES_REQUEST, "failed", "缺少数据库会话")

    from app.domain.after_sales.requests import RequestRepository

    try:
        resolved_type = RequestType(request_type)
    except ValueError:
        return ToolResult.error(
            ToolName.CREATE_AFTER_SALES_REQUEST,
            "invalid_argument",
            f"未知申请类型：{request_type}；合法值：{[item.value for item in RequestType]}",
        )

    repo = RequestRepository(session)
    outcome = repo.create_draft(
        case_id=case_id,
        request_type=resolved_type,
        summary=summary,
        payload=payload or {},
        idempotency_key=idempotency_key,
    )
    if outcome.error_code:
        return ToolResult.error(
            ToolName.CREATE_AFTER_SALES_REQUEST, outcome.error_code, outcome.message
        )
    return ToolResult(
        tool=ToolName.CREATE_AFTER_SALES_REQUEST,
        status="ok",
        data={
            "requestId": outcome.request_id,
            "requestStatus": outcome.request_status,
            "requestRevision": outcome.request_revision,
            "created": outcome.created,
            "note": "草稿已生成并进入待人工确认；批准不等于真实业务已完成。",
        },
        message=outcome.message,
        tool_request_id=tool_request_id,
    )


__all__ = [
    "create_request_draft",
    "dealer_lookup",
    "knowledge_search_tool",
    "order_lookup",
    "product_lookup",
    "record_case_fact",
    "record_rating",
    "tool_context_note",
    "troubleshooting_plan",
    "warranty_evaluate",
]
