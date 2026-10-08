"""Source-backed memory and deterministic checks before semantic verification."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.case_state.models import ConversationRow
from app.domain.consumer_service.models import AssistantRunRow, ServiceMemoryRow, ServiceMessageRow
from app.domain.consumer_service.product_evidence import mentioned_products, product_names
from app.errors import ModelOutputInvalid, NotFoundError
from app.repositories.consumer_service import ConsumerServiceRepository
from app.schemas.grounding import GroundingClaim, GroundingSource, MemoryItem, ServiceMemoryView

WORKFLOW_VERSION = "loreal-grounded-v2.42"
GENERAL_KNOWLEDGE_MARKER = "非具体商品依据"
MONEY = re.compile(r"[¥￥]\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*元")
IDENTIFIER = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]*\d{6,}(?![A-Za-z0-9])")
FACT_SIGNAL = re.compile(
    r"已经(?:发货|签收|到账|退款|补发|换货|完成|解决)|已(?:发货|签收|到账|退款|补发|换货|完成|解决)|"
    r"不含|成分|功效|适合.{0,10}(肤质|敏感|孕)|"
    r"\d{4}[-/年]\d{1,2}|[¥￥]\s*\d|\d+(?:\.\d+)?\s*(元|小时|天内)|"
    r"[A-Za-z]*\d{6,}"
)
DATE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")
STATUS = re.compile(r"已经(?:发货|签收|退款|到账|补发|换货|完成|解决)|已(?:发货|签收|退款|到账|补发|换货|完成|解决)|转账成功|退款成功")
BUSINESS_SUBMISSION = re.compile(
    r"(?:已|已经)(?:为您|帮您)?(?:提交|创建|登记|安排)(?:了)?"
    r"(?:打款|退款|退货|补发|换货)(?:申请)?|"
    r"(?:打款|退款|退货|补发|换货)(?:申请)?(?:已|已经)(?:提交|创建|登记|安排)"
)
UNSAFE = re.compile(
    r"(保证|一定|承诺).{0,16}(退款|到账|解决|发货|赔付)|"
    r"(今天|明天|后天|\d+\s*(小时|天)).{0,10}(到账|发货|补发|解决)|"
    r"(我|我们)[^，。！？；;：:\n]{0,6}(已(?!有)|已经|马上|立即|现在|这就|会)"
    r"[^，。！？；;：:\n]{0,10}(退款|打款|补发|换货|赔付)|"
    r"确诊|这是过敏|肯定是过敏|绝对安全|孕妇.{0,8}安全|孕期.{0,8}安全|"
    r"LOREAL_|SYSTEM_PROMPT|knowledgeEvidence"
)
MONEY_FIELDS = {"退款": "refundAmount", "单价": "unitPrice", "实付": "paidAmount", "支付金额": "paidAmount"}
DATE_FIELDS = {"下单": "orderedAt", "付款": "paidAt", "支付": "paidAt", "发货": "shippedAt",
               "创建": "createdAt", "完成": "completedAt"}
INTERNAL_STATUS = re.compile(
    r"(?<![A-Za-z_])(?:pending|in_progress|waiting_customer|waiting_external|resolved|"
    r"waiting_internal|operator_assisted|autonomous)(?![A-Za-z_])"
)
LOCAL_STATUS_LABELS = {
    "pending": "待受理", "in_progress": "处理中",
    "waiting_customer": "等待客户反馈", "waiting_internal": "等待内部处理",
    "waiting_external": "等待外部反馈", "resolved": "本地跟进完结",
}
UNAVAILABLE_LOGISTICS = re.compile(
    r"(?:我(?:们)?(?:会|再|将|可以|来)?(?:继续)?(?:帮您|为您)?|(?:再|继续)(?:帮您|为您))"
    r"\s*(?:查询|查看|核实|查)(?:一下)?(?:您的|这笔)?(?:订单)?(?:的)?"
    r"(?:实时物流|实时轨迹|派送进度|派送位置|快递位置)"
)
PRODUCT_ASSERTION = re.compile(
    r"不含|适合.{0,10}(肤质|敏感|孕)|"
    r"(?:这款|该款|本款|该商品|该产品|本产品|它).{0,20}"
    r"(?:功效|保湿|修护|美白|祛斑|抗皱|舒缓|含有|添加)"
)
PRODUCT_ATTRIBUTE_SIGNAL = re.compile(
    r"哑光|光泽|遮盖|质地|水润|成分|配方|功效|适用|持妆|不含|肤质|"
    r"色号|规格|售价|价格|元|[¥￥]|oil-free|noncomedogenic"
)
PRODUCT_QUALIFIER = re.compile(
    r"无法|不能|未提供|未知|不代表|不保证|不等于|不构成|是否|待核实|不作|未确认|不默认"
)
UNREFERENCED_PRODUCT_QUALIFIER = re.compile(
    r"不能|无法|尚不能|不保证|不代表|不等于|不构成|不作|未提供|未知|待核实"
)
PRODUCT_SELECTION_NOTE = re.compile(
    r"(?:您|你)?(?:可|可以)(?:按|根据|参考)官网(?:规格|说明|资料)(?:自行)?(?:取舍|选择|核对)"
)
PRODUCT_CLAUSE_BOUNDARY = re.compile(r"[。！？!?；;\n]|但是|不过|但")
EXPLICIT_CONCERN = re.compile(
    r"^(?:我|我们|本人)?(?:更|最|主要|一直)?(?:担心|顾虑|关心|在意|在乎|关注)"
)
CATALOG_ABSENCE = re.compile(
    r"(?:目录|商品库|知识库)[^，。！？?；;\n]{0,12}(?:(?<!有)没有|不存在|不包含)"
    r"[^，。！？?；;\n]{0,30}(?:记录|这款商品|这个商品)"
)


def _qualified_status(text: str, position: int) -> bool:
    prefix = re.split(r"[，。；;！？?\n]|但是|不过|但", text[:position])[-1]
    return bool(re.search(
        r"是否|核实|核对|不代表|不等于|不意味着|"
        r"(?:无法|不能|尚不能|未能)(?:(?:直接|据此|因此|就|简单|明确)){0,3}"
        r"(?:确认|判断|证明|认定|确定|断言|肯定|说)|未确认",
        prefix,
    ))


def validate_dialogue_fields(draft: Any, customer_messages: list[str]) -> list[str]:
    """Gate explicit no-more-actions preferences, not general dialogue semantics."""
    restrict_actions = False
    for text in customer_messages:
        for clause in re.split(r"[。！？!?，,；;\n]|但是|不过|但", text):
            if re.search(
                r"(?:不要|别|不用|不想|无需)[^。！？\n]{0,12}"
                r"(?:再|重复|解锁|按压|折腾|操作|试)|只.{0,6}(?:梳理|核对|整理).{0,8}资料",
                clause,
            ):
                restrict_actions = True
            elif not re.search(r"不愿意|不同意|不可以|不要|不用", clause) and re.search(
                r"(?:愿意|同意|可以|请).{0,10}(?:继续|重新|再).{0,8}(?:排查|尝试|操作)",
                clause,
            ):
                restrict_actions = False
    if not restrict_actions:
        return []
    action_patterns = (
        r"是否(?:已|已经)?尝试", r"再按", r"再试", r"重新解锁",
        r"清洁(?:泵头|泵口|出口)", r"更换泵头", r"检查瓶内吸管",
    )
    errors = []
    for field_name, values in (
        ("missing_information", draft.missing_information),
        ("next_steps", draft.next_steps),
    ):
        for value in values:
            actionable = any(
                re.search(pattern, clause)
                and not re.search(r"不要|不必|无需|不用|不要求|不建议|不再", clause)
                for clause in re.split(r"[，。；;\n]|但是|不过|但", value)
                for pattern in action_patterns
            )
            if actionable:
                errors.append(
                    f"{field_name}含操作排查项“{value[:80]}”，与消费者当前只核对资料的要求不符；"
                    "改为资料核对项或描述性信息，不要求消费者再次操作"
                )
    return list(dict.fromkeys(errors))


def _flatten(values: dict[str, Any]) -> str:
    labels = {
        "conversationId": "来源会话", "orderId": "订单号", "sku": "商品货号", "productName": "商品", "quantity": "数量",
        "paidAmount": "实付金额（元）", "unitPrice": "单价（元）", "sourceStatus": "源记录状态",
        "carrier": "快递", "trackingNo": "物流单号", "orderedAt": "下单时间",
        "paidAt": "付款时间", "shippedAt": "发货时间", "gift": "赠品",
        "workOrderId": "工单号", "type": "工单类型", "createdAt": "创建时间",
        "completedAt": "完成时间", "paymentType": "打款类型", "refundAmount": "退款金额（元）",
        "refundId": "退款编号", "transferStatus": "转账状态", "originalTrackingNo": "原物流单号",
        "reshipTrackingNo": "补发物流单号", "relatedTrackingNo": "关联物流单号",
        "reason": "事项原因", "returnReason": "退货原因", "solution": "处理方案",
        "symptomDescription": "不适自述", "stoppedUse": "是否停用", "soughtMedicalCare": "是否就医",
        "abnormal": "异常标记", "receiptAdvice": "签收建议", "productBatchNo": "产品批次",
        "ticketId": "本地工单", "localStatus": "本地跟进状态", "assignee": "负责人",
        "dueAt": "跟进期限", "revision": "记录版本",
        "localDetail": "本地事项资料（人工录入，非系统执行结果）",
    }
    return "\n".join(
        f"{labels.get(key, key)}：{LOCAL_STATUS_LABELS.get(str(value), value) if key == 'localStatus' else value}"
        for key, value in values.items() if value is not None
    )


def collect_sources(session: Session, conversation_id: str, context: Any = None) -> list[GroundingSource]:
    from app.domain.consumer_service.image_evidence import stored_image_sources
    from app.domain.consumer_service.tickets import events_for, list_tickets
    from app.domain.consumer_service.workspace import conversation_messages

    context = context or ConsumerServiceRepository(session).context(conversation_id)
    sources: dict[str, GroundingSource] = {}
    related = {conversation_id, *context.history_conversation_ids,
               *(order.conversation_id for order in context.orders)}
    local = session.get(ConversationRow, conversation_id)
    if local is not None:
        # Stable demo customer IDs are explicit links, unlike a guessed identity from a nickname.
        related.update(session.scalars(select(ConversationRow.conversation_id).where(
            ConversationRow.customer_id == local.customer_id,
        )))
    contexts = {conversation_id: context}
    imported_messages = {row.message_id: row for row in session.scalars(select(ServiceMessageRow).where(
        ServiceMessageRow.batch_id == context.batch_id,
        ServiceMessageRow.conversation_id.in_(related),
    ))}
    for cid in sorted(related):
        try:
            if cid != conversation_id:
                contexts[cid] = ConsumerServiceRepository(session).context(cid)
            messages = conversation_messages(session, cid)
        except NotFoundError:
            continue
        for message in messages:
            if not message.body.strip() or message.sender_role.value == "system":
                continue
            if message.sender_role.value == "assistant" and message.message_id not in imported_messages:
                continue
            kind = "customer_message" if message.sender_role.value == "customer" else "staff_message"
            source_id = f"message:{cid}:{message.message_id}"
            imported = imported_messages.get(message.message_id)
            sources[source_id] = GroundingSource(
                source_id=source_id, kind=kind, subject_id=cid,
                label=f"{'消费者自述' if kind == 'customer_message' else '历史客服发言'} · {cid}",
                text=message.body, occurred_at=message.created_at,
                fields={"conversationId": cid, **({
                    "orderId": imported.order_id, "workOrderId": imported.work_order_id,
                } if imported else {})},
            )
    orders = {o.order_id: o for c in contexts.values() for o in c.orders}
    work_orders = {w.work_order_id: w for c in contexts.values() for w in c.work_orders}
    for order in orders.values():
        fields = {
            "conversationId": order.conversation_id,
            "orderId": order.order_id, "sku": order.sku, "productName": order.product_name,
            "quantity": order.quantity, "paidAmount": str(Decimal(order.paid_amount_minor) / 100)
            if order.paid_amount_minor is not None else None,
            "unitPrice": str(Decimal(order.unit_price_minor) / 100) if order.unit_price_minor is not None else None,
            "sourceStatus": order.source_status, "carrier": order.carrier,
            "trackingNo": order.tracking_no, "orderedAt": order.ordered_at,
            "paidAt": order.paid_at, "shippedAt": order.shipped_at, "gift": order.gift,
        }
        source_id = f"order:{order.order_id}"
        sources[source_id] = GroundingSource(
            source_id=source_id, kind="order", subject_id=order.order_id, label=f"订单 {order.order_id}",
            text=_flatten(fields), fields=fields, occurred_at=order.ordered_at,
        )
    safe_work_fields = {
        "paymentType", "refundAmount", "refundId", "transferStatus", "originalTrackingNo",
        "reshipTrackingNo", "trackingNo", "relatedTrackingNo", "carrier", "productName",
        "sku", "quantity", "reason", "returnReason", "solution", "symptomDescription",
        "stoppedUse", "soughtMedicalCare", "abnormal", "receiptAdvice", "productBatchNo",
    }
    for work in work_orders.values():
        fields = {
            "conversationId": work.conversation_id,
            "workOrderId": work.work_order_id, "orderId": work.order_id,
            "type": work.work_order_type, "sourceStatus": work.source_status,
            "createdAt": work.created_at, "completedAt": work.completed_at,
            **{k: v for k, v in work.detail.items() if k in safe_work_fields},
        }
        source_id = f"work_order:{work.work_order_id}"
        sources[source_id] = GroundingSource(
            source_id=source_id, kind="work_order", subject_id=work.order_id or work.work_order_id,
            label=f"源工单 {work.work_order_id}", text=_flatten(fields), fields=fields,
            occurred_at=work.created_at,
        )
    for ticket in list_tickets(session):
        if ticket.conversation_id not in related and ticket.order_id not in orders:
            continue
        fields = {"ticketId": ticket.ticket_id, "localStatus": ticket.status,
                  "assignee": ticket.assignee, "dueAt": ticket.due_at, "revision": ticket.revision}
        if ticket.local_detail is not None:
            fields["localDetail"] = json.dumps(ticket.local_detail.dump(), ensure_ascii=False)
        source_id = f"followup:{ticket.ticket_id}"
        sources[source_id] = GroundingSource(
            source_id=source_id, kind="followup", subject_id=ticket.order_id or ticket.ticket_id,
            label=f"本地跟进 {ticket.ticket_id}", text=_flatten(fields), fields=fields,
            occurred_at=ticket.updated_at,
        )
        for event in events_for(session, ticket.ticket_id):
            source_id = f"followup_event:{event.event_id}"
            sources[source_id] = GroundingSource(
                source_id=source_id, kind="followup", subject_id=ticket.order_id or ticket.ticket_id,
                label=f"跟进备注 {ticket.ticket_id}", text=event.note,
                occurred_at=event.created_at,
            )
    for source in stored_image_sources(session, conversation_id):
        sources[source.source_id] = source
    return list(sources.values())


def source_hash(sources: list[GroundingSource]) -> str:
    payload = [s.dump() for s in sorted(sources, key=lambda s: s.source_id)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def memory_view(
    session: Session, conversation_id: str, sources: list[GroundingSource] | None = None,
) -> ServiceMemoryView:
    row = session.get(ServiceMemoryRow, conversation_id)
    sources = sources if sources is not None else collect_sources(session, conversation_id)
    if row is None:
        return ServiceMemoryView(conversation_id=conversation_id)
    items = [MemoryItem.model_validate(item) for item in json.loads(row.payload_json)]
    references = {item.source_ref for item in items}
    return ServiceMemoryView(
        conversation_id=conversation_id, revision=row.revision, stale=row.source_hash != source_hash(sources),
        items=items, sources=[s for s in sources if s.source_id in references],
        updated_at=row.updated_at.replace(tzinfo=UTC).isoformat(),
        verified=row.source_hash == source_hash(sources),
    )


def save_memory(
    session: Session, conversation_id: str, sources: list[GroundingSource],
    items: list[MemoryItem], model_id: str,
) -> None:
    row = session.get(ServiceMemoryRow, conversation_id)
    if row is None:
        row = ServiceMemoryRow(conversation_id=conversation_id, revision=0)
        session.add(row)
    row.source_hash = source_hash([s for s in sources if s.kind != "knowledge"])
    row.payload_json = json.dumps([item.dump() for item in items], ensure_ascii=False)
    row.revision += 1
    row.model_id, row.updated_at = model_id, datetime.now(UTC)
    session.flush()


def validate_memory(items: list[MemoryItem], catalog: dict[str, GroundingSource]) -> list[str]:
    errors = []
    for index, item in enumerate(items, 1):
        source = catalog.get(item.source_ref)
        if source is None or item.quote not in source.text:
            errors.append(f"第{index}条服务记忆未使用来源{item.source_ref}的逐字原文；从该来源复制连续片段，不拼接字段或改写")
        elif source.kind in {"knowledge", "image_observation"}:
            errors.append(f"第{index}条服务记忆引用知识或图片观察，不能作为消费者自述；移除这一项，仅从memorySourceCatalog抽取")
        elif item.category == "concern" and source.kind != "customer_message":
            errors.append("消费者关注点必须来自消费者自述")
        elif item.category == "attempted" and source.kind != "customer_message":
            errors.append(
                f"第{index}条attempted必须来自消费者本人自述；"
                "历史客服说已办理或承诺办理不证明消费者已尝试，也不证明业务已执行，移除这条已尝试记忆"
            )
        elif (item.category == "known" and source.kind == "customer_message"
              and EXPLICIT_CONCERN.match(item.quote.lstrip())):
            errors.append(
                f"第{index}条known引用了消费者明确的关注或担忧；"
                "将这段原文归入concern，不改写原文或推断情绪、健康属性"
            )
    return list(dict.fromkeys(errors))


def _product_claim_ownership_issues(
    body: str, claim: GroundingClaim, names: dict[str, tuple[str, ...]], cited_skus: set[str],
) -> list[str]:
    ranges = []
    start = 0
    for boundary in [*PRODUCT_CLAUSE_BOUNDARY.finditer(claim.text), None]:
        end = boundary.start() if boundary is not None else len(claim.text)
        clause = claim.text[start:end]
        if any(
            PRODUCT_ATTRIBUTE_SIGNAL.search(part) and not PRODUCT_QUALIFIER.search(part)
            and not PRODUCT_SELECTION_NOTE.fullmatch(part.strip())
            for part in re.split(r"[，,]", clause)
        ):
            ranges.append((start, clause))
        start = boundary.end() if boundary is not None else len(claim.text)
    issues = []
    # A delimited comparison has separate owners; a shared positive attribute does not.
    for occurrence in re.finditer(re.escape(claim.text), body):
        for offset, clause in ranges:
            owners = mentioned_products(clause, names)
            if not owners:
                prefix = PRODUCT_CLAUSE_BOUNDARY.split(body[:occurrence.start() + offset])[-1]
                owners = mentioned_products(prefix + clause, names)
            if len(owners) != 1 or not owners.issubset(cited_skus):
                issues.append(
                    f"事实子句“{clause[:60]}”商品身份或来源不唯一；"
                    "该子句写明商品名/登记简称，并引用该商品自己的专属来源；"
                    "不同商品属性分开陈述，不用一个来源证明另一款"
                )
    return list(dict.fromkeys(issues))


def validate_claims(
    body: str, claims: list[GroundingClaim], catalog: dict[str, GroundingSource],
    *, surface: str = "回复body",
) -> list[str]:
    from app.domain.consumer_service.image_evidence import image_attributed, validate_image_claim

    errors = []
    unsafe_match = UNSAFE.search(body)
    if unsafe_match:
        errors.append(
            f"回复片段“{unsafe_match.group()[:60]}”包含无权执行的承诺、医疗结论或内部信息；"
            "拒绝不当要求时只说明目前资料不能确认适用性，不复述确定安全保证或诊断措辞"
        )
    internal_match = INTERNAL_STATUS.search(body)
    if internal_match:
        errors.append(
            f"面向消费者的回复包含内部状态码“{internal_match.group()}”；"
            "删除内部状态，只回答有依据的订单/售后问题，不向客户解释本地处理状态"
        )
    for match in CATALOG_ABSENCE.finditer(body):
        prefix = re.split(r"[，。；;！？?\n]|但是|不过|但", body[:match.start()])[-1]
        negative = re.search(r"(?<!有)没有|不存在|不包含", match.group())
        if (negative and re.search(r"是否|是不是|有无", match.group()[:negative.start()])):
            continue
        if re.search(
            r"(?:无法|不能|尚不能)(?:直接|据此|因此)?(?:确认|确定|断言|判断|认定)$",
            prefix,
        ):
            continue
        if not re.search(r"本次检索|此次检索|检索到的|查到的|当前可见", prefix):
            errors.append(
                f"片段“{match.group()[:70]}”超出检索范围；本轮知识检索不是全目录盘点，"
                "删除全目录不存在的断言，改为“这款我这边暂时没查到相关资料”并补问成分表或商品照片"
            )
    for promise in UNAVAILABLE_LOGISTICS.finditer(body):
        prefix = body[max(0, promise.start() - 8):promise.start()]
        if not re.search(r"无法|不能|不支持|没有能力", prefix):
            errors.append("系统只能查询已有订单/工单记录，不能承诺查询实时派送信息")
    uncovered = body
    product_identities = product_names(catalog)
    cited_identifiers: set[str] = set()
    for index, claim in enumerate(claims, 1):
        if claim.text not in body:
            source_field = "body" if surface == "回复body" else "该建议字段"
            errors.append(
                f"第{index}条claims.text不在同条{surface}中；从{source_field}复制连续原文，"
                "不要使用知识摘录或事实概括代替正文片段，保留对应source_refs"
            )
            continue
        refs = [catalog.get(key) for key in claim.source_refs]
        missing_refs = [key for key, source in zip(claim.source_refs, refs, strict=True) if source is None]
        if missing_refs:
            errors.append(
                f"第{index}条claims.source_refs中来源{missing_refs[0]}不存在；"
                "只从sourceCatalog复制完整sourceId，recentConversation没有可引用来源ID"
            )
            continue
        sources = [s for s in refs if s is not None]
        errors.extend(validate_image_claim(claim.text, sources, body=body))
        image_sources = [source for source in sources if source.kind == "image_observation"]
        image_statement = bool(image_sources) and image_attributed(claim.text)
        scoped_products = [s for s in sources if s.kind == "knowledge"
                           and s.fields.get("scope") == "product_specific"]
        if scoped_products:
            valid_skus = {
                source.fields["productSku"] for source in scoped_products
                if isinstance(source.fields.get("productSku"), str)
                and source.fields.get("products") == [source.fields["productSku"]]
            }
            errors.extend(
                f"第{index}条事实：{issue}"
                for issue in _product_claim_ownership_issues(body, claim, product_identities, valid_skus)
            )
        for source in scoped_products:
            sku = source.fields.get("productSku")
            if not sku or source.fields.get("products") != [sku]:
                errors.append("商品专属来源缺少一致的单货号适用范围")
            if source.fields.get("provenance") == "team_fictional" and not re.search(r"演示|虚构", body):
                errors.append("使用团队虚构商品资料时，实际回复须说明来自演示商品资料，不当官方功效证据")
            if source.fields.get("market") == "US" and not re.search(r"美国|US", body):
                errors.append("美国商品资料须在实际回复注明美国版官网范围，不默认等同中国大陆商品")
        record_sources = [s for s in sources if s.kind in {"order", "work_order", "knowledge"}]
        order_ids = {str(s.fields["orderId"]) for s in catalog.values()
                     if s.kind in {"order", "work_order"} and s.fields.get("orderId")}
        mentioned = [key for key in order_ids if key in claim.text]
        scoped_records = [s for s in record_sources
                          if not mentioned or str(s.fields.get("orderId")) in mentioned]
        scope_text = "\n".join(s.text for s in sources)
        for submission in BUSINESS_SUBMISSION.finditer(claim.text):
            prefix = re.split(r"[。！？?\n]", claim.text[:submission.start()])[-1]
            if (not any(source.kind in {"order", "work_order"} for source in sources)
                    and not _qualified_status(claim.text, submission.start())
                    and not re.search(r"客服(?:曾|之前)?(?:告知|说|表示|回复)|您(?:说|表示|反馈)", prefix)):
                errors.append(
                    "历史客服发言不证明业务申请已提交；删除当前已执行的断言，"
                    "只回答本轮问题，若确需回顾则明确为此前客服告知并保留引用"
                )
        allowed_identifiers = set(IDENTIFIER.findall(scope_text))
        for identifier in IDENTIFIER.findall(claim.text):
            if identifier not in allowed_identifiers:
                errors.append("回复编号不在所引用的来源中")
            else:
                cited_identifiers.add(identifier)
        for match in DATE.finditer(claim.text):
            before = claim.text[max(0, match.start() - 20):match.start()]
            after = claim.text[match.end():match.end() + 8]
            before_labels = [m.group() for m in re.finditer("|".join(DATE_FIELDS), before)]
            after_label = re.search("|".join(DATE_FIELDS), after)
            label = after_label.group() if after_label else before_labels[-1] if before_labels else None
            field = DATE_FIELDS.get(label)
            date_text = ("\n".join(source.text for source in image_sources) if image_statement else
                         "\n".join(str(s.fields.get(field) or "") for s in scoped_records) if field else scope_text)
            dates = {tuple(int(v) for v in parts) for parts in DATE.findall(date_text)}
            if tuple(int(v) for v in match.groups()) not in dates:
                errors.append("回复日期不在所引用的来源中")
        source_statuses = " ".join(str(s.fields.get("sourceStatus") or "") for s in scoped_records)
        claim_positions = [m.start() for m in re.finditer(re.escape(claim.text), body)]
        for match in STATUS.finditer(claim.text):
            status = match.group().replace("已经", "已")
            if all(_qualified_status(body, position + match.start()) for position in claim_positions):
                continue
            if image_statement and any(
                status in str(line).replace("已经", "已")
                for source in image_sources for line in source.fields.get("visibleText", [])
            ):
                continue
            if status in source_statuses:
                continue
            payment_ok = status in {"已退款", "退款成功", "转账成功"} and any(
                s.kind == "work_order" and "退款" in str(s.fields.get("paymentType", ""))
                and str(s.fields.get("transferStatus", "")) in {"已转账", "转账成功", "成功", "已成功"}
                for s in scoped_records
            )
            work_ok = status == "已完成" and "工单" in claim.text and any(
                s.kind == "work_order" and s.fields.get("sourceStatus") in {"已完结", "已完成"}
                for s in scoped_records
            )
            attribution = r"您(?:已|已经)?(?:说|提到|反馈|表示|确认|说明|告知)"
            attributed = all(re.search(
                attribution,
                re.split(r"[，。；;！？?\n]|但是|不过|但",
                         body[:position + match.start()])[-1],
            ) for position in claim_positions) and any(
                s.kind == "customer_message" and any(
                    value.group().replace("已经", "已") == status
                    and not _qualified_status(s.text, value.start())
                    and not re.search(r"不|未|没有|不是", s.text[max(0, value.start() - 5):value.start()])
                    for value in STATUS.finditer(s.text)
                )
                for s in sources
            )
            if not (payment_ok or work_ok or attributed):
                errors.append(
                    f"第{index}条事实中的状态“{status}”不能由所引用的源字段证明；"
                    f"实际正文前文“{body[max(0, claim_positions[0] + match.start() - 30):claim_positions[0] + match.start()]}”；"
                    "工单完结不等于已补发、已签收或问题已解决"
                )
        for match in MONEY.finditer(claim.text):
            first, second = match.groups()
            amount = Decimal(first or second)
            prefix = re.split(r"[，。；;\n]", claim.text[:match.start()])[-1][-30:]
            labels = [m.group() for m in re.finditer("|".join(MONEY_FIELDS), prefix)]
            required_field = MONEY_FIELDS[labels[-1]] if labels else None
            keys = [required_field] if required_field else ["paidAmount", "unitPrice", "refundAmount"]
            values = []
            if image_statement:
                values.extend(
                    Decimal(a or b) for source in image_sources for a, b in MONEY.findall(source.text)
                )
            for source in record_sources:
                if source.kind == "knowledge" and required_field != "refundAmount":
                    values.extend(Decimal(a or b) for a, b in MONEY.findall(source.text))
                for key in keys:
                    if source.fields.get(key) is not None:
                        try:
                            values.append(Decimal(str(source.fields[key])))
                        except InvalidOperation:
                            continue
            if amount not in values:
                errors.append("回复金额与所引用的订单或工单不一致")
            if len(set(mentioned)) > 1:
                errors.append("每个金额陈述必须单独对应一笔订单")
            if mentioned and not image_statement:
                scoped_values = []
                for source in scoped_records:
                    for key in keys:
                        if source.fields.get(key) is not None:
                            try:
                                scoped_values.append(Decimal(str(source.fields[key])))
                            except InvalidOperation:
                                continue
                if amount not in scoped_values:
                    errors.append("金额被归到了错误的订单")
        knowledge = [s for s in record_sources if s.kind == "knowledge"
                     and s.fields.get("scope") != "general_consumer"
                     and GENERAL_KNOWLEDGE_MARKER not in s.text]
        for clause in re.split(r"[，。！？；;\n]|但是|不过|但", claim.text):
            if not PRODUCT_ASSERTION.search(clause):
                continue
            if re.search(r"无法确认|不能确认|未提供|未知|待核实|是否|没有.{0,8}资料", clause):
                continue
            if not knowledge or all(re.search(
                r"(成分|适用性|功效).{0,20}(未提供|未知|不作判断)", s.text,
            ) for s in knowledge):
                errors.append("商品成分、功效或适用性未有明确知识依据")
        uncovered = uncovered.replace(claim.text, "")
    for part in re.split(r"(?<=[。！？?，；;\n])|但是|不过|但", uncovered):
        if part.strip().endswith(("?", "？")) or "是否" in part:
            continue
        if any(not _qualified_status(part, match.start()) for match in BUSINESS_SUBMISSION.finditer(part)):
            errors.append("业务申请已提交/安排的陈述缺少业务来源引用，不能凭历史客服发言或无引用断言执行结果")
        if (mentioned_products(part, product_identities) and PRODUCT_ATTRIBUTE_SIGNAL.search(part)
                and not UNREFERENCED_PRODUCT_QUALIFIER.search(part)
                and not PRODUCT_SELECTION_NOTE.fullmatch(part.strip("，。！？?；;\n "))):
            errors.append(f"具体商品陈述“{part.strip()[:80]}”缺少逐项来源引用，引用该商品专属资料而非通用知识")
        for fact in FACT_SIGNAL.finditer(part):
            # Repeating a previously cited ID is a locator, not a new status,
            # amount or product assertion. Unknown IDs remain independently gated.
            if IDENTIFIER.fullmatch(fact.group()) and fact.group() in cited_identifiers:
                continue
            if STATUS.fullmatch(fact.group()) and _qualified_status(part, fact.start()):
                continue
            prefix = part[max(0, fact.start() - 25):fact.start()]
            suffix = part[fact.end():fact.end() + 15]
            topic_only = fact.group() in {"成分", "功效"} and (
                re.search(
                    r"(?:确认|核对|咨询|看看|看下|查看|对照|关注|留意|在意|担心|顾虑)"
                    r"[^。！？?，；;\n]{0,12}$",
                    prefix,
                )
                or re.match(r"(?:多留个心|格外在意|很在意|很正常)", suffix)
                or (suffix.startswith("表") and not re.search(r"显示|标明|写着|注明|载明", suffix))
            ) and not re.match(r"(?:是|为|含有|包含|有|具有|不含)", suffix)
            uncertain = re.search(r"(无法|不能|尚不能|不).{0,3}(确认|判断|保证|确定)|不清楚", prefix)
            unknown_product = fact.group() in {"成分", "功效"} and (
                re.search(r"未提供|没有提供|未知|尚不明确|无法确认|无法核实", suffix)
                or re.search(r"未提供|没有提供|未查到|查不到|缺少", prefix)
                or (re.search(r"没有\s*$", prefix) and re.match(r"资料|表", suffix))
            )
            not_guessing = fact.group() in {"成分", "功效"} and re.search(
                r"(?:不会|不能|不)(?:替您|为您|帮您)?"
                r"(?:(?:推荐|推)(?:具体)?(?:品牌|牌子|商品)(?:或|和|以及))?"
                r"(?:猜测|推测|猜)(?:具体)?(?:(?:商品|产品)(?:的)?)?\s*$",
                prefix,
            )
            if topic_only or uncertain or unknown_product or not_guessing:
                continue
            errors.append(f"回复事实片段缺少逐项来源引用：{part.strip()[:100]}")
    return list(dict.fromkeys(errors))


def validate_sources_budget(sources: list[GroundingSource]) -> None:
    if sum(len(s.text) for s in sources) > 60000:
        raise ModelOutputInvalid("服务上下文超出当前核验预算，需要人工复核")


def usage_for(calls: list[dict]) -> dict:
    return {
        "calls": len(calls),
        "promptTokens": sum(c["promptTokens"] for c in calls)
        if calls and all(c.get("promptTokens") is not None for c in calls) else None,
        "completionTokens": sum(c["completionTokens"] for c in calls)
        if calls and all(c.get("completionTokens") is not None for c in calls) else None,
        "inputCharacters": sum(c["inputCharacters"] for c in calls)
        if all(c.get("inputCharacters") is not None for c in calls) else None,
        "latencySeconds": round(sum(c.get("latencySeconds", 0) for c in calls), 3),
    }


def record_failure(session: Session, conversation_id: str, error: Exception) -> None:
    from app.audit.recorder import AuditContext, AuditRecorder

    calls = getattr(error, "workflow_calls", [])
    code = str(getattr(error, "code", type(error).__name__))
    trace = getattr(error, "workflow_steps", [])
    if trace and getattr(error, "workflow_issues", []):
        trace[-1] = {**trace[-1], "issues": error.workflow_issues}
    session.add(AssistantRunRow(
        run_id=f"run-{uuid.uuid4().hex[:16]}", conversation_id=conversation_id,
        input_hash=getattr(error, "workflow_input_hash", ""),
        model_id=calls[-1]["model"] if calls else "unavailable",
        is_mock=any(c.get("isMock", False) for c in calls),
        status="superseded" if code == "conflict" else "failed",
        trace_json=json.dumps(trace, ensure_ascii=False),
        usage_json=json.dumps(usage_for(calls)), error_code=code,
    ))
    AuditRecorder(session).record(
        AuditContext.new_turn(actor_type="agent", conversation_id=conversation_id),
        event_type="assistant_generation_failed",
        detail={"errorCode": code, "usage": usage_for(calls)},
    )
    session.flush()
