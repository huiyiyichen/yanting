"""AI接待辅助：读取欧莱雅服务轨迹，输出固定结构的客服辅助结果。"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.recorder import AuditContext, AuditRecorder, summarize
from app.domain.case_state.models import AuditEventRow
from app.domain.consumer_service.emotion import (
    emotion_trend,
)
from app.domain.consumer_service.models import (
    AssistantCacheRow,
    AssistantRunRow,
    ServiceAiObservationRow,
    ServiceConversationRow,
)
from app.domain.enums import (
    EmotionLevel,
    ServiceRiskLevel,
    ServiceRiskStatus,
    ServiceRiskType,
)
from app.errors import ProviderNotConfigured
from app.integrations.model_provider import ModelProvider
from app.repositories.consumer_service import ConsumerServiceRepository
from app.schemas.consumer_service import (
    AssistantActionRequest,
    AssistantReplySuggestionView,
    ConsumerServiceAssistantView,
    ReplyEmpathyDimension,
)

ASSISTANT_PROMPT_VERSION = "loreal-assistant-v1"
ASSISTANT_OUTPUT_SCHEMA_VERSION = "loreal-assistant.v4"


SYSTEM_PROMPT = """你是欧莱雅美妆电商客服工作台的接待辅助模块。
只输出 JSON，不要 markdown 或解释文字。
你只能使用输入中的聊天、订单和工单事实，不得补造订单、金额、状态、时间或身份。
不做医学诊断，不把不良反应判断为疾病或过敏结论。
不修改订单或工单，不发送消息，不把建议写成业务已完成。
emotion_level 只能是 calm、dissatisfied、angry、unknown。
reply_suggestions 至少一条，style 只能是 recommended、concise、reassuring。
不能承诺退款、打款、退货、补发、换货、赔付、处理完成或具体时限。
回复是否直接发送由服务模式控制，人工模式只填写草稿。
输出结构：
{
  "current_question": "当前消费者诉求",
  "service_summary": "服务轨迹摘要",
  "emotion_level": "calm|dissatisfied|angry|unknown",
  "missing_information": ["需要客服补充确认的信息"],
  "next_steps": ["客服下一步建议"],
  "reply_suggestions": [
    {"style": "recommended|concise|reassuring",
     "segments": [{"text":"面向消费者的连续话语","source_refs":["有事实时的真实来源ID"]}]}
  ],
  "handoff_required": false
}"""

AUTO_RECEPTION_PROMPT = """当前为AI自动接待模式，recommended回复会直接发送给消费者。
你就是正在接待的AI客服，使用自然、具体的中文，不说“建议客服”“请让客服核对”等内部话语。
回复正文只使用自然中文；英文护理标签翻译成“无油配方”“不易堵塞毛孔”，品牌名、商品名、货号和型号保留原样。
回应消费者的具体问题和担忧，结合订单、售后和历史记录直接说明相关信息。
围绕本轮最相关差异给出结论和取舍，用短句；重要事实不能因简洁而省略。
商品首次可用完整名，后续用输入中登记且不歧义的简称，不在每句重复完整名称。
同一不确定边界集中说明一次，不对每款重复整段免责声明；每款具体属性仍在自己的片段附来源。
消费者只要求商品比较时，先给比较结论，再分别说明关键差异；不额外增加清洁、护理或再次试用建议。
不把整段资料复制成回复；套装区别一次说明清楚，不重复列举商品名、编号及相同限制。
商品比较通常控制在2–5句、约260字以内，按“结论→核心组成差异→与消费者偏好的关系”组织；资料边界只收束一句。
已经提供过的信息不要重复索要。消费者补充一句短话时，结合前文理解，不当成独立问题。
普通咨询可以继续澄清；不要假称已经联系仓库、提交退款、完成换货或执行任何系统中未发生的动作。
不要编造商品成分、功效、使用禁忌、承诺时限或医疗结论。
若消费者要求人工、需要执行真实售后动作、出现高风险不良反应或证据冲突，handoff_required为true。
普通订单/物流查询、查询售后进度、信息澄清和一般不满由你继续接待，handoff_required为false。
不要仅因为存在历史售后工单就转人工；判断当前诉求是否需要人工实际操作。
若消费者明确只要求查询已有记录，即便没有实时轨迹也说明当前未知信息，继续AI接待，不把主动催单或联系仓库追加为当前任务。
需要转人工时，recommended先回应具体困扰并说明已查到的事实和转交原因，不假称已完成售后。
输出仍遵守系统JSON契约；自动接待只生成一条recommended回复，避免同时生成不会发送的候选。
回复突出当前问题所需的信息，不堆砌无关订单字段；不输出内部风险标签或知识原文。
面向消费者只说明与本轮问题有关的业务信息，不展示内部工单、本地跟进或状态码。
核对订单号后只能再次查询已有订单和工单记录，不能承诺查询实时派送进度或快递位置。
需要最新派送信息时可以请消费者使用快递官方渠道，不假称本系统已接通实时物流。"""

def _risk_summary(session: Session, conversation_id: str):
    from app.domain.consumer_service.risk import risk_alert_view, signal_attention
    from app.domain.consumer_service.risk_rules import RANK, evaluate_risks

    rows = [row for row in evaluate_risks(session) if row.conversation_id == conversation_id]
    if not rows:
        return [ServiceRiskType.UNKNOWN], ServiceRiskLevel.UNKNOWN, "", [], ServiceRiskStatus.PENDING
    statuses = {row.risk_status for row in rows}
    status = next(s for s in ("pending", "in_progress", "resolved", "ignored") if s in statuses)
    current = [
        view for view in (risk_alert_view(row, session) for row in rows)
        if signal_attention(
            view.risk_status.value, signal_active=view.signal_active,
            analysis_stale=bool(view.conditions.get("analysisStale")),
        ) == "active"
    ]
    if not current:
        return [ServiceRiskType.UNKNOWN], ServiceRiskLevel.UNKNOWN, "", [], ServiceRiskStatus(status)
    return (
        [view.risk_type for view in current],
        max((view.risk_level for view in current), key=RANK.get),
        "；".join(dict.fromkeys(view.trigger_summary for view in current)),
        list(dict.fromkeys(ref for view in current for ref in view.evidence_refs)),
        ServiceRiskStatus(status),
    )


def _adopted_count(session: Session, conversation_id: str) -> int:
    rows = session.scalars(select(AuditEventRow).where(
        AuditEventRow.conversation_id == conversation_id,
        AuditEventRow.event_type == "consumer_suggestion_action",
    ))
    total = 0
    for row in rows:
        try:
            detail = json.loads(row.detail_json)
        except (TypeError, ValueError):
            continue
        if detail.get("action") == "adopt":
            total += 1
    return total


class ConsumerServiceAssistant:
    def __init__(self, session: Session, provider: ModelProvider, *, runtime: Any = None) -> None:
        self._session = session
        self._provider = provider
        self._repository = ConsumerServiceRepository(session)
        self._runtime = runtime

    def build(
        self, conversation_id: str, *, automatic: bool = False,
        still_current: Callable[[], bool] | None = None,
        require_breakpoints: bool = False,
        timeout_seconds: float | None = None,
    ) -> ConsumerServiceAssistantView:
        if not self._provider.available():
            raise ProviderNotConfigured(
                "客服 AI 辅助模型未配置",
                detail="模型不可用时不生成成功的客服辅助结果",
            )

        from app.domain.consumer_service.grounded_workflow import run_grounded_workflow
        from app.domain.consumer_service.grounding import save_memory, usage_for
        from app.domain.consumer_service.personalization import advice_views
        state = run_grounded_workflow(
            self._session, self._provider, conversation_id, automatic=automatic,
            knowledge_search=self._knowledge, still_current=still_current,
            require_breakpoints=require_breakpoints,
            timeout_seconds=timeout_seconds if timeout_seconds is not None else
            self._runtime.settings.auto_reply_timeout_seconds if automatic and self._runtime else None,
            settings=self._runtime.settings if self._runtime else None,
        )
        parsed, context, result = state["draft"], state["context"], state["result"]
        assert parsed is not None
        messages, input_hash = state["messages"], state["input_hash"]
        latest_message, prompt_version = state["latest_message"], state["prompt_version"]
        evidence, knowledge_status = state["knowledge"], state["knowledge_status"]
        customer_messages = [m.body for m in messages if m.sender_role.value == "customer" and m.body]
        source_message_record_id = next((
            e.message.source_record_id for e in reversed(context.timeline)
            if e.message and e.message.sender_role == "customer"
        ), None)
        emotion = EmotionLevel.parse_or_unknown(parsed.emotion_level)
        trend = emotion_trend(customer_messages)
        imported_id = self._session.scalar(
            select(ServiceConversationRow.record_id).where(
                ServiceConversationRow.batch_id == context.batch_id,
                ServiceConversationRow.conversation_id == conversation_id,
            )
        )
        suggestions: list[AssistantReplySuggestionView] = []
        for item in parsed.reply_suggestions:
            body = item.body
            customer_text = " ".join(customer_messages)
            emotion_present = bool(
                any(term in body for term in ("理解", "抱歉", "着急", "担心", "不容易", "辛苦", "别担心"))
                or (emotion.value in {"angry", "dissatisfied"} and any(
                    term in body for term in ("您", "亲")
                ))
            )
            business_present = bool(
                any(term in body for term in (
                    "订单", "物流", "快递", "退款", "补发", "退货", "工单", "批次",
                    "核对", "查询", "查看", "确认", "照片", "图片",
                ))
            )
            personalized_present = bool(
                customer_text and any(
                    token in body for token in (
                        "肤质", "T区", "两颊", "卡粉", "担心", "在意", "已经试过",
                        "2604B", "订单", "补发",
                    )
                )
            )
            dimensions = [
                ReplyEmpathyDimension(
                    key="emotion_response", label="情绪回应",
                    status="present" if emotion_present else "missing",
                    reason="回应了消费者的担忧或情绪"
                    if emotion_present else "没有直接承接消费者情绪",
                ),
                ReplyEmpathyDimension(
                    key="business_handling", label="业务处理",
                    status="present" if business_present else "missing",
                    reason="包含当前问题的处理信息或下一步"
                    if business_present else "没有给出具体业务处理信息",
                ),
                ReplyEmpathyDimension(
                    key="personalized", label="个性化",
                    status="present" if personalized_present else "missing",
                    reason="使用了消费者本轮提供的关键信息"
                    if personalized_present else "没有引用本轮消费者的具体信息",
                ),
            ]
            suggestions.append(AssistantReplySuggestionView(
                style=item.style, body=body, claims=item.claims,
                empathy_dimensions=dimensions,
            ))
        personalized_advice = advice_views(
            parsed.personalized_advice, {source.source_id: source for source in state["sources"]},
        )

        observation_id = f"obs-{uuid.uuid4().hex[:12]}"
        audit_context = AuditContext.new_turn(
            actor_type="agent",
            conversation_id=conversation_id,
            model_name=result.model,
            prompt_version=prompt_version,
            output_schema_version=ASSISTANT_OUTPUT_SCHEMA_VERSION,
        )
        audit = AuditRecorder(self._session)
        for call in state["calls"]:
            audit.record_model_call(
                audit_context, input_text=latest_message, latency_seconds=call["latencySeconds"],
                output_schema_version=ASSISTANT_OUTPUT_SCHEMA_VERSION, is_mock=call["isMock"],
                detail={**call, "deliveryMode": "automatic" if automatic else "draft"},
            )
        usage = usage_for(state["calls"])
        from app.domain.consumer_service.image_evidence import save_image_observations

        save_image_observations(self._session, state["images"], provider=self._provider)
        save_memory(self._session, conversation_id, state["sources"], parsed.memory, result.model)
        self._session.add(AssistantRunRow(
            run_id=observation_id, conversation_id=conversation_id, input_hash=input_hash,
            model_id=result.model, is_mock=any(c["isMock"] for c in state["calls"]),
            status="verified", trace_json=json.dumps([s.dump() for s in state["steps"]], ensure_ascii=False),
            usage_json=json.dumps(usage),
        ))
        from app.domain.consumer_service.service_breakpoints import save_assessment

        save_assessment(
            self._session, conversation_id, context.batch_id, observation_id, state["sources"],
            state.get("service_findings"),
        )
        risk_types, risk_level, risk_reason, evidence_refs, risk_status = _risk_summary(
            self._session, conversation_id,
        )

        conversation_record_id = self._session.scalar(
            select(ServiceConversationRow.record_id).where(
                ServiceConversationRow.batch_id == context.batch_id,
                ServiceConversationRow.conversation_id == conversation_id,
            )
        )
        observation = ServiceAiObservationRow(
            observation_id=observation_id,
            batch_id=context.batch_id,
            conversation_record_id=conversation_record_id,
            conversation_id=conversation_id,
            source_message_record_id=source_message_record_id if imported_id else None,
            emotion_level=emotion.value,
            emotion_trend=trend.value,
            risk_types_json=json.dumps([item.value for item in risk_types], ensure_ascii=False),
            risk_level=risk_level.value,
            risk_status=risk_status.value,
            risk_reason=risk_reason,
            current_question=parsed.current_question.strip() or latest_message[:500],
            service_summary=parsed.service_summary.strip(),
            missing_information_json=json.dumps(
                [item.strip()[:200] for item in parsed.missing_information if item.strip()],
                ensure_ascii=False,
            ),
            next_steps_json=json.dumps(
                [item.strip()[:200] for item in parsed.next_steps if item.strip()],
                ensure_ascii=False,
            ),
            reply_suggestions_json=json.dumps(
                [item.model_dump(mode="json") for item in suggestions],
                ensure_ascii=False,
            ),
            evidence_refs_json=json.dumps(evidence_refs, ensure_ascii=False),
            model_id=result.model,
            is_mock=any(c["isMock"] for c in state["calls"]),
            prompt_version=prompt_version,
        )
        if imported_id:
            self._session.add(observation)
        audit.record(
            audit_context,
            event_type="consumer_assistant_generated",
            input_text=latest_message,
            risk_level=risk_level.value,
            detail={
                "observationId": observation_id,
                "riskTypes": [item.value for item in risk_types],
                "emotionLevel": emotion.value,
                "emotionTrend": trend.value,
                "replyCount": len(suggestions),
                "summary": summarize(parsed.service_summary, limit=120),
                "isMock": any(c["isMock"] for c in state["calls"]),
            },
        )
        self._session.flush()

        view = ConsumerServiceAssistantView(
            observation_id=observation_id,
            dataset_id=context.dataset_id,
            batch_id=context.batch_id,
            conversation_id=conversation_id,
            current_question=observation.current_question,
            service_summary=observation.service_summary,
            emotion_level=emotion,
            emotion_trend=trend,
            risk_types=risk_types,
            risk_level=risk_level,
            risk_status=risk_status,
            risk_reason=risk_reason,
            evidence_refs=evidence_refs,
            missing_information=json.loads(observation.missing_information_json),
            next_steps=json.loads(observation.next_steps_json),
            reply_suggestions=suggestions,
            adopted_count=_adopted_count(self._session, conversation_id),
            personalized_advice=personalized_advice,
            is_mock=any(c["isMock"] for c in state["calls"]),
            model_id=result.model,
            prompt_version=prompt_version,
            input_hash=input_hash,
            knowledge_status=knowledge_status,
            knowledge_evidence=evidence,
            handoff_required=parsed.handoff_required,
            delivery_mode="automatic" if automatic else "draft",
            intent=parsed.intent,
            memory_items=parsed.memory,
            grounding_sources=state["sources"],
            verification_status="verified",
            workflow_steps=state["steps"],
            model_usage=usage,
            service_breakpoints=state.get("service_findings"),
        )
        cache = self._session.get(AssistantCacheRow, conversation_id)
        if cache is None:
            cache = AssistantCacheRow(conversation_id=conversation_id)
            self._session.add(cache)
        cache.input_hash = input_hash
        cache.payload_json = view.model_dump_json(by_alias=True)
        self._session.flush()
        return view

    def _knowledge(self, query: str) -> tuple[list[dict[str, Any]], str]:
        if self._runtime is None:
            return [], "unavailable"
        from app.domain.enums import Visibility
        from app.knowledge.models import KnowledgeBaseRow
        from app.knowledge.retrieval import RetrievalRequest, retrieve

        try:
            base_ids = list(self._session.scalars(select(KnowledgeBaseRow.knowledge_base_id).where(
                KnowledgeBaseRow.knowledge_base_id.like("loreal-%"),
                KnowledgeBaseRow.enabled.is_(True),
            )))
            if not base_ids:
                return [], "not_found"
            skus = set(re.findall(r"\b(?:XC|XL|XW)\d{5}\b", query.upper()))
            result = retrieve(
                self._session,
                settings=self._runtime.settings,
                embedding_provider=self._runtime.embedding_provider,
                request=RetrievalRequest(
                    # Current official demo is a mainland-China beauty commerce dataset.
                    query=query, audience=Visibility.INTERNAL, knowledge_base_ids=base_ids,
                    country_code="CN",
                    product_model=next(iter(skus)) if len(skus) == 1 else None,
                ),
                rerank_provider=self._runtime.rerank_provider,
            )
            return [
                {**item.model_dump(mode="json"), "source_text": result.source_texts[item.chunk_id]}
                for item in result.evidence
            ], result.hit_status.value
        except Exception:
            return [], "failed"


def read_assistant(session: Session, conversation_id: str) -> ConsumerServiceAssistantView | None:
    from app.domain.consumer_service.workspace import assistant_input_hash

    cache = session.get(AssistantCacheRow, conversation_id)
    if cache is None:
        return None
    view = ConsumerServiceAssistantView.model_validate_json(cache.payload_json)
    view.adopted_count = _adopted_count(session, conversation_id)
    view.stale = cache.input_hash != assistant_input_hash(session, conversation_id)
    return view


def record_suggestion_action(
    session: Session, conversation_id: str, payload: AssistantActionRequest
):
    from app.errors import ConflictError, NotFoundError

    view = read_assistant(session, conversation_id)
    if view is None:
        raise NotFoundError("暂无建议")
    if view.verification_status != "verified":
        raise ConflictError("回复尚未完成依据核验")
    if view.stale or view.input_hash != payload.input_hash:
        raise ConflictError("建议已过期")
    if payload.style not in [item.style for item in view.reply_suggestions]:
        raise NotFoundError("建议不存在")
    AuditRecorder(session).record(
        AuditContext.new_turn(actor_type="operator", conversation_id=conversation_id),
        event_type="consumer_suggestion_action",
        detail={"style": payload.style, "action": payload.action, "inputHash": view.input_hash},
    )
    return {"ok": True}
