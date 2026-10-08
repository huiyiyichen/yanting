"""案件编排器：把三个核心功能串成一条纵向流程。

流程（PRD 第 2.4 节）：
    接收输入 → 多模态理解(F1) → 候选/消歧 → 诉求识别与分流(F2)
    → 检索证据(F3) → 订单/质保/授权核验 → 低风险排障或生成申请草稿
    → 人工确认（如需） → 收尾与评价

幂等与恢复：
- 每次编排带 `idempotency_key`，工具调用经 ToolGateway 复用首次结果，
  因此 LangGraph 中断恢复重跑同一节点不会产生重复副作用；
- 案件状态与消息一律落库，浏览器不承担事实来源。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date
from typing import Any

from sqlalchemy.orm import Session

from app.audit.recorder import AuditContext, AuditRecorder, summarize
from app.config import Settings
from app.domain.agent.contracts import (
    INTENT_TO_REQUEST_TYPE,
    AgentDecision,
    CaseFacts,
)
from app.domain.agent.routing import (
    ROUTE_DEALER_VERIFICATION,
    ROUTE_HUMAN_REVIEW,
    ROUTE_REQUEST_DRAFT,
    ROUTE_TROUBLESHOOTING,
    ROUTE_WARRANTY_CHECK,
    decide_route,
    primary_request_type,
    sort_intents,
)
from app.domain.agent.understanding import UnderstandingAnalyzer
from app.domain.case_state.models import CaseRow
from app.domain.enums import (
    CaseStatus,
    ConversationStage,
    CustomerIntent,
    DealerAuthorizationStatus,
    KnowledgeHitStatus,
    RequestStatus,
    SenderRole,
    ToolName,
    WarrantyStatus,
)
from app.errors import AnkerAgentError
from app.integrations.embedding_provider import EmbeddingProvider
from app.logging_setup import get_logger, log_event
from app.repositories.conversation_repository import ConversationRepository
from app.tool_gateway.contracts import ToolContext
from app.tool_gateway.gateway import ToolGateway

logger = get_logger(__name__)

PROMPT_VERSION = "s2-understanding-v1"

#: 这些路径要**办理售后**，型号与国家/地区是硬前置条件，缺失时必须先补问。
#: 其余路径（如排障解答）可以先给依据支持的答案，再补问（见 `_compose_reply`）。
ROUTES_REQUIRING_FACTS = frozenset(
    {ROUTE_REQUEST_DRAFT, ROUTE_WARRANTY_CHECK, ROUTE_DEALER_VERIFICATION}
)
# 理解模块输出结构版本：模型输出契约变化时必须递增，审计据此复盘
UNDERSTANDING_SCHEMA_VERSION = "understanding.v1"


@dataclass
class OrchestratorDeps:
    """编排所需的运行时依赖。显式传入便于测试替换。"""

    session: Session
    settings: Settings
    embedding_provider: EmbeddingProvider
    gateway: ToolGateway
    analyzer: UnderstandingAnalyzer
    audit: AuditRecorder | None = None
    #: 回复生成用的模型提供者。为 None 时只用模板（测试与离线环境）
    reply_model: Any = None
    #: 取「启用中的 REPLY 提示词模板」（Prompt 管理可编辑）；返回 None 时用代码常量
    reply_prompt_resolver: Any = None


class CaseOrchestrator:
    def __init__(self, deps: OrchestratorDeps) -> None:
        self._deps = deps
        self._session = deps.session
        self._settings = deps.settings
        self._gateway = deps.gateway
        self._repo = ConversationRepository(deps.session)
        # 审计是硬要求：未显式传入时按会话自动创建，避免静默漏记
        self._audit = deps.audit or AuditRecorder(deps.session)

    # ------------------------------------------------------------------ 入口

    def handle_customer_message(
        self,
        *,
        conversation_id: str,
        message: str,
        client_message_key: str,
        image_data_urls: list[str] | None = None,
        attachment_refs: list[dict[str, Any]] | None = None,
    ) -> AgentDecision:
        """处理一条客户消息并返回完整决策。"""

        conversation = self._repo.get_conversation(conversation_id)
        if conversation is None:
            from app.errors import NotFoundError

            raise NotFoundError(f"会话不存在：{conversation_id}")

        # 1) 幂等落库客户消息
        stored, message_created = self._repo.append_message(
            conversation,
            sender_role=SenderRole.CUSTOMER,
            body=message,
            client_message_key=client_message_key,
            # 带上附件元数据：消息本身要能表达「这条消息带了哪些图」，
            # 否则前端渲染不出附件、复盘时也看不出客户是否传过图。
            attachments=attachment_refs,
        )

        # 2) 首条有效客户消息创建案件
        case, _ = self._repo.create_case_for_conversation(conversation)

        if not message_created:
            # 重复消息：返回当前案件快照与**原始**消息/回复 ID，不重复执行任何副作用
            existing = self._find_message_by_key(conversation_id, client_message_key)
            reply_row = self._find_reply_after(conversation_id, existing)
            return self._snapshot_decision(
                case,
                note="重复消息（幂等键相同），未重复处理",
                customer_message_id=existing.message_id if existing else None,
                reply_message_id=reply_row.message_id if reply_row else None,
            )

        # 3) 确定性规则优先：客户明确要求转人工 → 立即转接（不需要先调用模型）
        if wants_human_handover(message):
            return self._handover_to_human(
                conversation=conversation,
                case=case,
                customer_message_id=stored.message_id,
                message=message,
            )

        # 审计上下文：一个用户轮次共用一个 trace_id，便于把模型调用与工具调用串起来
        audit_context = AuditContext.new_turn(
            actor_type="customer",
            conversation_id=conversation_id,
            case_id=case.case_id,
            model_name=getattr(self._deps.analyzer, "model_id", None),
            prompt_version=PROMPT_VERSION,
            output_schema_version=UNDERSTANDING_SCHEMA_VERSION,
        )

        # 3) F1 理解
        confirmed = self._facts_from_case(case)
        history = [
            item.body for item in self._repo.list_messages(conversation_id)[-6:] if item.body
        ]
        understanding = self._deps.analyzer.analyze(
            message=message,
            image_data_urls=image_data_urls,
            confirmed_facts=confirmed,
            history=history[:-1],
        )
        self._audit.record_model_call(
            audit_context,
            input_text=message,
            latency_seconds=understanding.latency_seconds,
            output_schema_version=UNDERSTANDING_SCHEMA_VERSION,
            is_mock=understanding.is_mock,
            detail={
                "intents": [item.value for item in understanding.intents],
                "faultType": understanding.facts.fault_type.value,
                "emotionLevel": understanding.emotion_level.value,
                "complaintRisk": understanding.complaint_risk.value,
                "hasImages": bool(image_data_urls),
            },
        )
        facts = understanding.facts
        intents = sort_intents(understanding.intents)

        # 4) 产品候选与消歧（候选只确认关联对象，**不修改源订单**）
        candidates: list[dict[str, Any]] = []
        requires_disambiguation = False
        if facts.product_model:
            product_result = self._gateway.invoke(
                ToolName.PRODUCT_LOOKUP,
                {"productModel": facts.product_model},
            )
            # 型号精确匹配失败时，退回按**名称**召回。
            # 实测：模型可能把「A1 Pro 无线吸尘器」整串当成 product_model，
            # 而夹具里的型号键是「A1 Pro」——精确匹配于是返回 not_found、
            # 候选为空，多候选消歧（AC-03）就静默失效，用户既看不到候选，
            # 也拿不到「请确认是哪一款」的追问。
            if product_result.status == "not_found" or not product_result.ok:
                product_result = self._gateway.invoke(
                    ToolName.PRODUCT_LOOKUP,
                    {"query": facts.product_model},
                )
            if product_result.ok:
                candidates = list(product_result.data.get("candidates") or [])
                requires_disambiguation = bool(product_result.data.get("requiresDisambiguation"))
                if len(candidates) == 1:
                    only = candidates[0]
                    facts.product_id = only.get("productId")
                    facts.product_category = only.get("productCategory")
                    # 名称召回唯一命中时，把模型还原成标准型号，避免后续
                    # 检索与工具拿着「A1 Pro 无线吸尘器」这种非标准值去过滤
                    if only.get("productModel"):
                        facts.product_model = str(only["productModel"])
                elif candidates:
                    # 多候选时也要把型号收敛到**标准型号**（「A1 Pro 无线吸尘器」
                    # → 「A1 Pro」）。知识片段按标准型号打标，不收敛会让过滤条件
                    # 永远匹配不上，检索恒为 not_found（实测：候选列出来了、
                    # 但依据 0 条）。收敛只改型号写法，**不代表确认了具体产品**：
                    # product_id 仍为空，消歧提示照常发出。
                    canonical = candidates[0].get("productModel")
                    if canonical:
                        facts.product_model = str(canonical)

        # 5) 订单与事实补充
        order_result = self._gateway.invoke(
            ToolName.ORDER_LOOKUP, {"customerId": conversation.customer_id}
        )
        if order_result.ok:
            orders = order_result.data.get("orders") or []
            if len(orders) == 1:
                single = orders[0]
                if not facts.product_model:
                    facts.product_model = single.get("productModel")
                    facts.product_id = single.get("productId")
                facts.order_id = single.get("orderId")
                facts.country_code = facts.country_code or single.get("countryCode")
                facts.purchase_channel = facts.purchase_channel or single.get("purchaseChannel")
                facts.seller_name_raw = facts.seller_name_raw or single.get("sellerNameRaw")

        # 6) 检索证据（客户视角只取 customer_visible）
        retrieval_result = self._gateway.invoke(
            ToolName.KNOWLEDGE_SEARCH,
            {
                "query": message,
                "productModel": facts.product_model,
                "countryCode": facts.country_code,
                "purchaseChannel": facts.purchase_channel,
            },
            context=ToolContext(
                read_only=True,
                case_id=case.case_id,
                conversation_id=conversation_id,
                requested_by="agent",
            ),
        )
        evidence: list[dict[str, Any]] = []
        retrieval_id: str | None = None
        hit_status: KnowledgeHitStatus | None = None
        if retrieval_result.status in {"ok", "empty", "not_found", "conflict"}:
            evidence = list(retrieval_result.data.get("evidence") or [])
            retrieval_id = retrieval_result.data.get("retrievalId")
            raw_status = retrieval_result.data.get("hitStatus")
            hit_status = KnowledgeHitStatus(raw_status) if raw_status else None

        # 6b) 把本次检索证据以**不可变副本**写入审计事件。
        # 这样即使之后重建索引、替换快照，历史案件仍能按当时的版本复盘（AC-28）。
        if retrieval_id:
            self._repo.record_event(
                case,
                event_type="knowledge_retrieval",
                actor_type="agent",
                detail={
                    "retrievalId": retrieval_id,
                    "snapshotId": retrieval_result.data.get("snapshotId"),
                    "hitStatus": hit_status.value if hit_status else None,
                    "query": message,
                    "productModel": facts.product_model,
                    "countryCode": facts.country_code,
                    "evidence": evidence,
                },
            )

        # 7) 质保与授权核验（按路径需要）
        warranty_status = self._evaluate_warranty(facts)
        dealer_status = self._verify_dealer(facts)

        # 8) 分流
        route = decide_route(
            facts=facts,
            intents=intents,
            emotion=understanding.emotion_level,
            complaint_risk=understanding.complaint_risk,
            knowledge_hit_status=hit_status,
            warranty_status=warranty_status,
            dealer_status=dealer_status,
            clarification_attempts=case.clarification_attempts,
        )

        # 9) 先落库案件事实。
        # 顺序很重要：`create_after_sales_request` 会读数据库校验
        # 「型号与国家/地区是否已确认」，若先建草稿再落库，
        # 校验读到的仍是上一轮的旧值，草稿会被误判为信息不足而失败
        # （已实测踩到：工具返回 conflict，提示缺少 product_model/country_code）。
        self._persist_decision(
            case,
            facts,
            intents,
            understanding,
            route,
            evidence,
            retrieval_id,
            hit_status,
            warranty_status,
            dealer_status,
            None,
        )

        # 10) 再按路径执行动作
        request_draft: dict[str, Any] | None = None
        if route.route == ROUTE_REQUEST_DRAFT:
            request_draft = self._create_request_draft(case, intents, facts, route)
        if facts.product_model and requires_disambiguation and not facts.product_id:
            route.notes.append("产品型号存在多个候选，需用户确认后才能进入高风险办理（AC-03）")

        # 11) 依草稿结果更新案件状态（有待确认申请时进入待确认，但不自动关闭）
        if request_draft and request_draft.get("requestId"):
            self._repo.set_case_status(case, CaseStatus.PENDING_REVIEW)
            self._session.flush()

        # 11) 生成面向用户的回复：回答型路径优先用模型，规则分支与异常情况走模板
        missing_required = facts.missing_required()
        reply = None
        if route.route not in ROUTES_REQUIRING_FACTS or not missing_required:
            reply = self._generate_reply(
                message=message,
                facts=facts,
                evidence=evidence,
                missing=missing_required,
                candidates=candidates if requires_disambiguation else [],
                communication_style=route.communication_style,
                audit_context=audit_context,
                has_images=bool(image_data_urls),
            )
        if reply is None:
            reply = self._compose_reply(
                route_name=route.route,
                facts=facts,
                intents=intents,
                candidates=candidates if requires_disambiguation else [],
                # 显式传递「是否需要产品消歧」：不传的话，`candidates` 被清空后
                # 回复里既不会列候选、也不会请用户确认，多候选案件就静默地被
                # 当成已确认处理（AC-03 要求必须补问/确认）。
                requires_disambiguation=requires_disambiguation,
                evidence=evidence,
                warranty_status=warranty_status,
                dealer_status=dealer_status,
                request_draft=request_draft,
                communication_style=route.communication_style,
                # 「我看了照片」这句话只有在**确实带了图**时才允许出现：
                # 否则模型偶尔凭空给出可见线索时，回复会谎称看过照片（幻觉）。
                has_images=bool(image_data_urls),
            )
        self._repo.append_message(
            conversation,
            sender_role=SenderRole.ASSISTANT,
            body=reply,
            client_message_key=f"reply-{client_message_key}",
        )
        reply_row = self._find_message_by_key(conversation_id, f"reply-{client_message_key}")

        # 12) 结束时的评价入口
        rating_requested = self._maybe_request_rating(case)

        # 13) 审计：记录本轮全部工具调用与最终分流结论。
        # 工具失败/超时同样记录（工程规范第 7 节）。
        self._audit.record_tool_calls(
            audit_context,
            call_log=self._gateway.call_log(),
            knowledge_snapshot_version=self._deps.embedding_provider.model_id or None,
        )
        self._audit.record(
            audit_context,
            event_type="agent_decision",
            input_text=message,
            knowledge_snapshot_version=retrieval_id,
            human_confirmation_status=("pending" if request_draft else "not_required"),
            detail={
                "serviceRoute": route.route,
                "caseStatus": case.case_status,
                "stage": case.conversation_stage,
                "knowledgeHitStatus": hit_status.value if hit_status else None,
                "warrantyStatus": warranty_status.value if warranty_status else None,
                "dealerAuthorizationStatus": (dealer_status.value if dealer_status else None),
                "humanInterventionRequired": route.human_intervention_required,
                "humanInterventionReason": route.human_intervention_reason,
                "requestDraftCreated": bool(request_draft),
                # 只保存脱敏摘要，不保存完整回复原文
                "replySummary": summarize(reply, limit=120),
            },
        )

        return AgentDecision(
            stage=ConversationStage(case.conversation_stage),
            reply=reply,
            facts=facts,
            customer_intents=intents,
            emotion_level=understanding.emotion_level,
            complaint_risk=understanding.complaint_risk,
            service_route=route.route,
            allowed_actions=route.allowed_actions,
            missing_facts=facts.missing_required(),
            product_candidates=candidates,
            uncertainty_flags=understanding.uncertainty_flags,
            evidence=evidence,
            retrieval_id=retrieval_id,
            knowledge_hit_status=hit_status,
            warranty_status=warranty_status,
            dealer_authorization_status=dealer_status,
            request_draft=request_draft,
            human_intervention_required=route.human_intervention_required,
            human_intervention_reason=route.human_intervention_reason,
            tool_calls=self._gateway.call_log(),
            model_id=understanding.model_id,
            prompt_version=PROMPT_VERSION,
            trace_id=audit_context.trace_id,
            case_status=CaseStatus(case.case_status),
            customer_message_id=stored.message_id,
            reply_message_id=reply_row.message_id if reply_row else None,
            rating_requested=rating_requested,
            notes=route.notes,
        )

    # ------------------------------------------------------------- 私有步骤

    def _facts_from_case(self, case: CaseRow) -> CaseFacts:
        return CaseFacts(
            product_model=case.product_model,
            product_id=case.product_id,
            product_category=case.product_category,
            country_code=case.country_code,
            purchase_channel=case.purchase_channel,
            seller_name_raw=case.seller_name_raw,
        )

    def _evaluate_warranty(self, facts: CaseFacts) -> WarrantyStatus | None:
        if not facts.order_id:
            return None
        result = self._gateway.invoke(ToolName.WARRANTY_EVALUATE, {"orderId": facts.order_id})
        if not result.ok and result.status != "ok":
            raw = result.data.get("warrantyStatus")
            if raw:
                return WarrantyStatus(raw)
            return WarrantyStatus.QUERY_FAILED
        raw = result.data.get("warrantyStatus")
        return WarrantyStatus(raw) if raw else None

    def _verify_dealer(self, facts: CaseFacts) -> DealerAuthorizationStatus | None:
        """仅在需要确认购买渠道时核验；不提供授权名单供用户挑选。"""

        if not facts.seller_name_raw:
            return None
        if facts.purchase_channel not in {"third_party_seller", "marketplace"}:
            return None
        result = self._gateway.invoke(
            ToolName.DEALER_LOOKUP,
            {
                "sellerNameRaw": facts.seller_name_raw,
                "countryCode": facts.country_code,
                "purchaseChannel": facts.purchase_channel,
            },
        )
        raw = result.data.get("authorizationStatus")
        return DealerAuthorizationStatus(raw) if raw else None

    def _create_request_draft(
        self,
        case: CaseRow,
        intents: list[CustomerIntent],
        facts: CaseFacts,
        route: Any,
    ) -> dict[str, Any] | None:
        request_type = primary_request_type(intents)
        if request_type is None:
            return None
        result = self._gateway.invoke(
            ToolName.CREATE_AFTER_SALES_REQUEST,
            {
                "caseId": case.case_id,
                "requestType": request_type.value,
                "summary": facts.phenomenon or "用户提出售后申请",
                "payload": {
                    "intents": [item.value for item in intents],
                    "warrantyStatus": case.warranty_status,
                    "dealerAuthorizationStatus": case.dealer_authorization_status,
                },
            },
        )
        if not result.ok:
            route.notes.append(f"未能生成申请草稿：{result.message}")
            return None
        return dict(result.data)

    def _persist_decision(
        self,
        case: CaseRow,
        facts: CaseFacts,
        intents: list[CustomerIntent],
        understanding: Any,
        route: Any,
        evidence: list[dict[str, Any]],
        retrieval_id: str | None,
        hit_status: KnowledgeHitStatus | None,
        warranty_status: WarrantyStatus | None,
        dealer_status: DealerAuthorizationStatus | None,
        request_draft: dict[str, Any] | None,
    ) -> None:
        # 标准卖家名只在核验成功时写入，且不覆盖原始名
        standard_name: str | None = None
        if dealer_status is DealerAuthorizationStatus.AUTHORIZED and facts.seller_name_raw:
            lookup = self._gateway.invoke(
                ToolName.DEALER_LOOKUP,
                {
                    "sellerNameRaw": facts.seller_name_raw,
                    "countryCode": facts.country_code,
                    "purchaseChannel": facts.purchase_channel,
                },
            )
            standard_name = lookup.data.get("sellerNameStandard")

        self._repo.update_case_facts(
            case,
            product_id=facts.product_id,
            product_model=facts.product_model,
            product_category=facts.product_category,
            country_code=facts.country_code,
            purchase_channel=facts.purchase_channel,
            seller_name_raw=facts.seller_name_raw,
            seller_name_standard=standard_name,
            intents=[item.value for item in intents],
            facts=facts.to_dict(),
            missing_facts=facts.missing_required(),
            emotion_level=understanding.emotion_level,
            complaint_risk=understanding.complaint_risk,
            warranty_status=warranty_status.value if warranty_status else None,
            dealer_authorization_status=dealer_status.value if dealer_status else None,
            knowledge_hit_status=hit_status.value if hit_status else None,
            retrieval_id=retrieval_id,
        )

        # 阶段推进
        if facts.missing_required():
            self._safe_stage(case, ConversationStage.DISAMBIGUATION)
            case.clarification_attempts += 1
        elif route.route == ROUTE_DEALER_VERIFICATION or route.route == ROUTE_WARRANTY_CHECK:
            self._safe_stage(case, ConversationStage.ELIGIBILITY)
        elif route.route == ROUTE_TROUBLESHOOTING:
            self._safe_stage(case, ConversationStage.DIAGNOSIS)
        elif route.route == ROUTE_HUMAN_REVIEW:
            self._safe_stage(case, ConversationStage.AWAITING_CONFIRMATION)
            self._repo.set_case_status(case, CaseStatus.PENDING_REVIEW)
        elif route.route == ROUTE_REQUEST_DRAFT:
            self._safe_stage(case, ConversationStage.AWAITING_CONFIRMATION)

        if request_draft and request_draft.get("requestId"):
            # 有待人工确认的申请：案件进入待确认，但**不**自动关闭
            self._repo.set_case_status(case, CaseStatus.PENDING_REVIEW)

        self._session.flush()

    def _safe_stage(self, case: CaseRow, target: ConversationStage) -> None:
        from app.errors import ValidationRejected

        try:
            self._repo.set_stage(case, target)
        except ValidationRejected:
            # 阶段回退属于正常流程（例如从诊断回到补问），这里不视为错误
            logger.debug("stage transition skipped: %s -> %s", case.conversation_stage, target)

    def _maybe_request_rating(self, case: CaseRow) -> bool:
        open_requests = self._repo.list_open_requests(case.case_id)
        if open_requests:
            return False
        if CaseStatus(case.case_status) is not CaseStatus.CLOSED:
            return False
        result = self._gateway.invoke(
            ToolName.RECORD_RATING, {"caseId": case.case_id, "action": "request"}
        )
        return result.ok

    def _snapshot_decision(
        self,
        case: CaseRow,
        *,
        note: str,
        customer_message_id: str | None = None,
        reply_message_id: str | None = None,
    ) -> AgentDecision:
        from app.domain.enums import ComplaintRisk, EmotionLevel

        intents = [CustomerIntent(item) for item in _json_list(case.customer_intents_json)]
        return AgentDecision(
            stage=ConversationStage(case.conversation_stage),
            reply="",
            facts=self._facts_from_case(case),
            customer_intents=intents,
            emotion_level=EmotionLevel(case.emotion_level),
            complaint_risk=ComplaintRisk(case.complaint_risk),
            service_route="idempotent_replay",
            allowed_actions=[],
            missing_facts=_json_list(case.missing_facts_json),
            case_status=CaseStatus(case.case_status),
            customer_message_id=customer_message_id,
            reply_message_id=reply_message_id,
            is_idempotent_replay=True,
            notes=[note],
        )

    def _find_message_by_key(self, conversation_id: str, client_message_key: str) -> Any | None:
        for row in self._repo.list_messages(conversation_id):
            if row.client_message_key == client_message_key:
                return row
        return None

    def _find_reply_after(self, conversation_id: str, customer_message: Any | None) -> Any | None:
        """找出该客户消息之后紧随的自动回复。"""

        if customer_message is None:
            return None
        rows = self._repo.list_messages(conversation_id)
        seen = False
        for row in rows:
            if row.message_id == customer_message.message_id:
                seen = True
                continue
            if seen and row.sender_role in {"assistant", "operator"}:
                return row
        return None

    #: 命中这些措辞的模型回复一律作废（承诺类红线），回退模板
    _FORBIDDEN_REPLY_PATTERNS = (
        "保证",
        "一定能",
        "百分之百",
        "已退款",
        "已发货",
        "已赔付",
        "已派单",
        "承诺赔付",
    )

    def _generate_reply(
        self,
        *,
        message: str,
        facts: CaseFacts,
        evidence: list[dict[str, Any]],
        missing: list[str],
        candidates: list[dict[str, Any]],
        communication_style: str,
        audit_context: AuditContext,
        has_images: bool = False,
    ) -> str | None:
        """让模型生成回复；返回 None 表示「不要用模型结果，走模板」。

        校验不通过**不抛错**：回复生成是可选增强，不能因为它让整条消息处理失败。
        每次回退都写一条 `reply_fallback` 审计，便于统计真实回退率。
        """

        provider = self._deps.reply_model
        if provider is None or not getattr(provider, "available", lambda: False)():
            return None

        from app.domain.agent.reply import (
            REPLY_PROMPT_VERSION,
            REPLY_SYSTEM_PROMPT,
            build_reply_prompt,
        )

        system_prompt = REPLY_SYSTEM_PROMPT
        if self._deps.reply_prompt_resolver is not None:
            resolved = self._deps.reply_prompt_resolver()
            if resolved and resolved.strip():
                system_prompt = resolved

        facts_lines = [
            f"产品型号：{facts.product_model}" if facts.product_model else "",
            f"国家/地区：{facts.country_code}" if facts.country_code else "",
            f"购买渠道：{facts.purchase_channel}" if facts.purchase_channel else "",
            f"故障现象：{facts.phenomenon}" if facts.phenomenon else "",
            # 只在**确实带了图**时才把线索写进提示词：否则模型会据此谎称看过照片
            "图片可见线索：" + "；".join(facts.observed_from_image)
            if (has_images and facts.observed_from_image)
            else "",
        ]
        evidence_lines = [
            f"- {item.get('document_title') or '相关资料'}：{(item.get('quoted_excerpt') or '')[:200]}"
            for item in evidence[:3]
        ]

        style_text = {
            "acknowledge_then_solve": "先简短致意，再解决问题",
            "brief_reassure_then_solve": "先安抚，再解决问题",
            "neutral": "中性、简洁",
        }.get(communication_style, "中性、简洁")

        prompt = build_reply_prompt(
            message=message,
            facts_lines=[line for line in facts_lines if line],
            evidence_lines=evidence_lines,
            missing=missing,
            style=style_text,
            candidates=[
                f"{item.get('displayName')}（{item.get('productCategory')}）" for item in candidates
            ],
            has_images=has_images,
        )

        try:
            from app.integrations.model_provider import ChatMessage

            result = self._deps.reply_model.complete(
                [
                    ChatMessage(role="system", content=system_prompt),
                    ChatMessage(role="user", content=prompt),
                ],
                temperature=0.2,
                max_tokens=600,
            )
        except Exception as exc:
            self._audit.record(
                audit_context,
                event_type="reply_fallback",
                detail={"reason": type(exc).__name__, "promptVersion": REPLY_PROMPT_VERSION},
            )
            return None

        text = (result.text or "").strip()
        hit = next((word for word in self._FORBIDDEN_REPLY_PATTERNS if word in text), None)
        # 结构化输出（JSON）不是给客户看的回复：实测模型会把理解用的 JSON 直接返回，
        # 放过去客户就会看到一坨 JSON。宁可回退模板。
        looks_structured = text.startswith("{") or text.startswith("[") or '"phenomenon"' in text
        if looks_structured:
            hit = hit or "structured_output"
        if not text or len(text) < 10 or len(text) > 800 or hit:
            self._audit.record(
                audit_context,
                event_type="reply_fallback",
                detail={
                    "reason": "forbidden_phrase" if hit else "invalid_length_or_empty",
                    "matched": hit,
                    "promptVersion": REPLY_PROMPT_VERSION,
                },
            )
            return None

        self._audit.record(
            audit_context,
            event_type="reply_generated",
            detail={
                "model": getattr(result, "model", None),
                "latencySeconds": getattr(result, "latency_seconds", None),
                "promptVersion": REPLY_PROMPT_VERSION,
                "chars": len(text),
            },
        )
        return text

    def _handover_to_human(
        self,
        *,
        conversation: Any,
        case: Any,
        customer_message_id: str,
        message: str,
    ) -> AgentDecision:
        """把会话切到「客服已接管」，并给对方一个明确、不夸张的回复。

        三件事必须做对：
        1. **真的改模式**：AI 之后不再自动发言（`operator_assisted`），否则「转人工」
           只是一句话，用户下一条消息还是机器人回复；
        2. **不留空回复**：明确告知已记录并要求补充哪些信息；
        3. **入审计**：这是「谁可以自动发言」的变更，必须留痕（actor 是客户）。
        """

        from app.domain.enums import ServiceMode

        changed = self._repo.set_service_mode(conversation, ServiceMode.OPERATOR_ASSISTED)
        if changed:
            self._session.flush()
            self._audit.record(
                AuditContext.new_turn(
                    actor_type="customer",
                    conversation_id=conversation.conversation_id,
                    case_id=case.case_id,
                ),
                event_type="service_mode_changed",
                detail={
                    "fromMode": "autonomous",
                    "toMode": ServiceMode.OPERATOR_ASSISTED.value,
                    "reason": "customer_requested_handover",
                },
            )

        reply_body = (
            "好的，已经为您转接人工客服。\n"
            "本 Demo 里由售后客服在工作台查看并回复，不需要您重复描述；"
            "AI 不会在人工处理期间自动替您答复。\n"
            "如果方便，请把产品完整型号（包装或机身标签上的名称）与购买国家或地区一并告知，"
            "客服核对会更快。"
        )
        reply_row, _ = self._repo.append_message(
            conversation,
            sender_role=SenderRole.ASSISTANT,
            body=reply_body,
            client_message_key=None,
        )
        self._session.flush()
        return self._snapshot_decision(
            case,
            note="客户要求转人工：已切换到客服接管并回复",
            customer_message_id=customer_message_id,
            reply_message_id=reply_row.message_id,
        )

    def _compose_reply(
        self,
        *,
        route_name: str,
        facts: CaseFacts,
        intents: list[CustomerIntent],
        candidates: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        warranty_status: WarrantyStatus | None,
        dealer_status: DealerAuthorizationStatus | None,
        request_draft: dict[str, Any] | None,
        communication_style: str,
        requires_disambiguation: bool = False,
        has_images: bool = False,
    ) -> str:
        """生成用户可见回复。

        约束：不展示内部条款原文、不承诺金额或时限、不把草稿说成已完成。

        关键取舍（对应 PRD「Agent 自主完成理解、追问、检索与低风险排障」）：
        型号与国家/地区是**办理售后申请**的必要事实，但不是回答通用问题的
        前提。若已检索到适用依据且本路径不要求办理，就先给出依据支持的答案，
        再把缺失事实作为可选的补充项——否则「吸力变弱怎么排查」这类问题只会
        得到一段追问，检索到的排障依据完全没被用上（实测 20 条样本全部如此）。
        """

        lines: list[str] = []
        if communication_style == "brief_reassure_then_solve":
            lines.append("非常抱歉给您带来困扰，我先帮您把问题查清楚。")
        elif communication_style == "acknowledge_then_solve":
            lines.append("抱歉这次体验没有达到预期，我来帮您处理。")

        # 客户发了图就先说「我从图里看到了什么」。
        # 为什么必须写出来：线索原本只落到案件事实里（`observedFromImage`），
        # 客户在对话里完全看不到「图被看过了」——实测客户问「照片里两个指示灯
        # 分别是什么状态、序列号多少」，回复却只给了通用排障步骤，看图能力等于白做。
        # 这里只复述**可见现象**，不据此下根因结论（根因仍来自依据与工具）；
        # 且必须 `has_images` 为真——没有图却说「我看了照片」就是幻觉。
        if has_images and facts.observed_from_image:
            clues = "；".join(item[:120] for item in facts.observed_from_image[:3])
            lines.append(f"我先看了您发的照片，可以看到：{clues}。")

        missing = facts.missing_required()
        # 只有真正要办理售后时才让缺失事实阻断回答
        facts_block = bool(missing) and route_name in ROUTES_REQUIRING_FACTS

        if facts_block and candidates:
            lines.append("这个型号对应多个产品，需要您先确认是哪一款：")
            for index, item in enumerate(candidates, start=1):
                lines.append(f"{index}. {item.get('displayName')}（{item.get('productCategory')}）")
            lines.append("如果都不符合，请告诉我包装上的完整型号，我再帮您核对。")
            return "\n".join(lines)

        if facts_block and not evidence:
            # 没有可用依据、又要办理：先补问，不猜测
            prompts = {
                "product_model": "请告诉我产品的完整型号（包装或机身标签上的名称）",
                "country_code": "请告诉我购买的国家或地区",
            }
            lines.append("为了给您准确的方案，还需要确认：")
            for field in missing:
                lines.append(f"- {prompts.get(field, field)}")
            return "\n".join(lines)

        if route_name == ROUTE_DEALER_VERIFICATION:
            if dealer_status is DealerAuthorizationStatus.MULTIPLE_MATCHES:
                lines.append(
                    "您提供的店铺名称对应多个记录，为免判断错误，请补充完整店铺名或购买凭证。"
                )
            elif dealer_status is DealerAuthorizationStatus.QUERY_FAILED:
                lines.append("授权核验暂时查询失败，我会稍后重试；这不代表您的渠道有问题。")
            else:
                lines.append("为了核对购买渠道，请补充实际购买店铺的名称或购买凭证。")
            return "\n".join(lines)

        if route_name == ROUTE_REQUEST_DRAFT and request_draft:
            lines.append("我已经帮您整理好申请内容，正在等待售后客服确认。")
            lines.append("需要说明：确认通过仅表示申请被受理，退款或换货实际完成还需要后续处理。")
            return "\n".join(lines)

        if warranty_status is WarrantyStatus.IN_WARRANTY:
            lines.append("根据订单信息，您的设备在保修期内。")
        elif warranty_status is WarrantyStatus.OUT_OF_WARRANTY:
            lines.append("根据订单信息，您的设备已超出保修期，我可以提供付费方案供您参考。")
        elif warranty_status is WarrantyStatus.UNKNOWN:
            lines.append("目前还无法判断保修状态，需要补充购买凭证。")
        elif warranty_status is WarrantyStatus.QUERY_FAILED:
            lines.append("保修状态查询失败，我会重试；暂时不能给出结论。")

        if evidence:
            # 证据来自 knowledge_search 工具的 `data`，其内部键为 snake_case
            # （与知识契约一致）；不要在编排层按 camelCase 读取，否则会静默取到空值。
            first = evidence[0]
            title = first.get("document_title") or "相关资料"
            excerpt = (first.get("quoted_excerpt") or "").strip()
            lines.append(f"根据《{title}》的说明：")
            if excerpt:
                lines.append(excerpt[:300])
            lines.append("您可以先按上面的步骤试一下，有任何变化随时告诉我。")
        elif route_name in {ROUTE_TROUBLESHOOTING, ROUTE_REQUEST_DRAFT, ROUTE_WARRANTY_CHECK}:
            # 没有可用依据时不能编造结论，但**也不能返回空回复**：
            # 必须明确告知无法确认，并说明下一步。
            lines.append("我暂时没有查到适用于您这款产品的处理依据，所以不做猜测。")
            lines.append("我会把情况记录下来转给售后客服进一步确认，稍后给您答复。")

        if CustomerIntent.COMPLAINT in intents:
            lines.append("您反馈的投诉问题我会一并记录并转交处理。")

        # 多候选产品必须请用户确认（AC-03）。
        # 这条要放在「已给答案」之后：先把依据支持的结论给出来，再请用户认领具体产品，
        # 否则用户会觉得答非所问。缺少这一步时，多候选案件在回复里看不出任何「待确认」，
        # AC-03 的「必须补问/确认」就没有落地。
        if requires_disambiguation and candidates:
            lines.append("另外，为了确认是哪一款产品，请您确认：")
            for index, item in enumerate(candidates, start=1):
                lines.append(f"{index}. {item.get('displayName')}（{item.get('productCategory')}）")
            lines.append("回复对应编号即可；如果都不符合，请告诉我包装上的完整型号。")

        # 已给出答案后，再把办理所需的缺失事实作为可选项补上：
        # 追问与「先回答」并不冲突，但顺序必须是先给价值、再要信息。
        if missing and not facts_block:
            prompts = {
                "product_model": "产品完整型号（包装或机身标签上的名称）",
                "country_code": "购买的国家或地区",
            }
            wanted = "、".join(prompts.get(field, field) for field in missing)
            lines.append(f"如果后续需要办理售后，请再补充：{wanted}。")

        if not lines:
            # 兜底：任何路径都不允许产生空回复（空回复会被前端当成本次没有回应）
            lines.append("已收到您的信息，我正在核对相关记录，稍后给您明确答复。")
            if facts.product_model:
                lines.append(f"目前已确认产品型号：{facts.product_model}。")
        return "\n".join(lines)


#: 客户明确要求转人工的说法。命中即**立即**转接（用户 2026-09-25 补充的规则）。
#: 与 PRD 既有规则不冲突：那条是「愤怒本身不触发转接」，这条是「客户主动要求要照做」。
_HANDOVER_PATTERNS = (
    "转人工",
    "转接人工",
    "人工客服",
    "人工服务",
    "找人工",
    "要人工",
    "转客服",
    "真人客服",
    "联系人工",
)


def wants_human_handover(message: str) -> bool:
    """客户是否明确要求转人工。"""

    text = (message or "").strip()
    if not text:
        return False
    return any(pattern in text for pattern in _HANDOVER_PATTERNS)


def _json_list(raw: str | None) -> list[str]:
    import json

    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def today() -> date:
    from datetime import datetime

    return datetime.now(UTC).date()


__all__ = [
    "INTENT_TO_REQUEST_TYPE",
    "AnkerAgentError",
    "CaseOrchestrator",
    "OrchestratorDeps",
    "RequestStatus",
    "log_event",
]
