"""Evidence gates and presentation for advice drafted inside the reception graph."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.consumer_service.cited_text import ActionText, ReasonText, render_parts
from app.domain.consumer_service.grounding import (
    GENERAL_KNOWLEDGE_MARKER,
    validate_claims,
)
from app.domain.consumer_service.product_evidence import mentioned_products, product_names
from app.schemas.consumer_service import PersonalizedAdviceEvidence, PersonalizedAdviceView
from app.schemas.grounding import GroundingClaim, GroundingSource


class AdviceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ref: str = Field(min_length=1)
    quote: str = Field(min_length=1, max_length=240)


class AdviceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["routine", "makeup", "product_selection", "trial_safety"]
    title: str = Field(min_length=1, max_length=40)
    scope: Literal["general_consumer", "product_specific"] = "general_consumer"
    product_sku: str | None = Field(default=None, max_length=80)
    evidence: list[AdviceCitation] = Field(min_length=2, max_length=4)


class CitedAdviceDraft(AdviceIdentity):
    action_parts: list[ActionText] = Field(min_length=1, max_length=3)
    rationale_parts: list[ReasonText] = Field(min_length=1, max_length=3)


class AdviceCandidate(AdviceIdentity):
    action: str = Field(min_length=1, max_length=240)
    rationale: str = Field(min_length=1, max_length=180)
    claims: list[GroundingClaim] = Field(default_factory=list, max_length=6)

    @model_validator(mode="before")
    @classmethod
    def from_parts(cls, value):
        if not isinstance(value, dict) or not ({"action_parts", "rationale_parts"} & value.keys()):
            return value
        if value.get("action") or value.get("rationale") or value.get("claims"):
            raise ValueError("分段格式不同时填写action/rationale/claims")
        wire = CitedAdviceDraft.model_validate({
            key: item for key, item in value.items() if key not in {"action", "rationale", "claims"}
        })
        action, action_claims = render_parts(wire.action_parts)
        rationale, rationale_claims = render_parts(wire.rationale_parts)
        return {
            **wire.model_dump(exclude={"action_parts", "rationale_parts"}),
            "action": action, "rationale": rationale,
            "claims": [*action_claims, *rationale_claims],
        }


PERSONALIZATION_INSTRUCTIONS = """同时输出personalized_advice数组，最多2项。
每项结构为{"category":"routine|makeup|product_selection|trial_safety","title":"简短建议标题",
"action_parts":[{"text":"可实行方案或商品事实","source_refs":["真实sourceId"]}],
"rationale_parts":[{"text":"匹配消费者偏好或取舍的理由","source_refs":["真实sourceId"]}],
"scope":"general_consumer|product_specific","product_sku":null或资料对应货号,
"evidence":[{"source_ref":"消费者sourceId","quote":"连续原文"},
{"source_ref":"知识sourceId","quote":"真正支持该建议的连续原文"}]}。
action_parts最多3段，每段80字符；rationale_parts最多3段，每段60字符，标题40字符。
每段自己写连续话语并附来源，程序拼成action/rationale和claims；不要另外填写action、rationale或claims，不重复抄写话语。
商品事实段与消费者理由段分别附商品知识/消费者自述来源；对照两款时各款事实拆成自己的段，不让一段同时陈述两款。
只对当前美妆咨询生成；物流、售后执行等话题及需要转人工时返回[]，不沿用旧话题的护理建议。
将最新消费者纠正和已核验的记忆一起理解，不把历史肤质永久化；未提到T区时不凭空添加T区。
已经试过或明确不想重复的措施不作为新的行动；不再以“先清洁和保湿”敷衍已经试过保湿的消费者。
可以改为知识支持的其他低风险选择维度；没有新方案依据时返回[]并在回复坦诚说明，不凑卡片或泛化追问。
尊重不推品牌、不推荐商品、只核对资料等明确偏好；不因“不要推荐”包含推荐一词而生成商品推荐或商品资料缺项。
action必须是有依据的方案或筛选条件，而非复述担忧、模板道歉、提示证据不足或只是追问。
通用方案至少同时引用消费者自述和general_consumer知识，scope=general_consumer、product_sku=null。
具体商品选择scope=product_specific，必须引用消费者自述和fields.productSku等于product_sku的商品专属资料；
每项指定一个主要候选，说明匹配点与取舍，不按热门程度推销；理由可与另一款对照，但各款属性分别用对应资料引用，不用同一条claims混写两款事实。
quote只复制真正支持方案的连续原文，不截取无关的开头。通用资料不能代替具体货号的成分、妆效或适用性证据。
资料性质为team_fictional时，action和实际回复都明确说“按演示商品资料”，不假称真实功效或临床适用性。
具体商品属性片段写明商品名、标识或登记的唯一简称，并附自己的知识source_refs；不把另一商品资料混用。
REF-US是内部资料标识，不当厂商货号；action优先用完整商品名，且注明美国版官网范围，不默认等同国内配方或在售情况。
缺少商品专属资料不输出具体商品选择，不能从商品名推断属性，也不能保证适用或解决问题。
不要把通用护理建议描述成保证解决卡粉或专业底妆技法；没有底妆技法依据就不编造技巧。
新产品小范围试用只适用于尚未出现不适的咨询；消费者已红痒肿、刺痛或就医时不要求再次试用，转人工。
日期、次数、天数、成分等具体陈述的片段同样须附实际来源，不因分段而免除核验。
recommended回复须自然表达本轮主要建议，不只在内部建议数组填方案而给消费者模板话术。
只比较商品时不附加消费者未请求的护理措施；结论和主要差异简短表达，不重复抄写整段知识或相同边界。
本数组也经过来源门禁与独立核验，不得绕过回复安全边界。"""

PERSONALIZATION_REVIEW = """逐项核验personalized_advice和消费者实际收到的回复：
建议是否针对当前问题、最新自述及仍有效的关注？明确纠正后的旧肤质不得继续使用。
已尝试措施和明确拒绝重做的操作不得重新推荐；不推品牌/商品时不追加商品资料缺项。
action是否提供有依据的具体方案或筛选条件，而非仅复述、道歉或追问？
evidence中的知识原文是否实际支持action和rationale，而非仅词语相似？消费者证据是否仍有效？
通用护理不等于底妆技法或特定商品适用性，不得保证解决妆效或虚构SKU结论。
商品选择必须绑定同一货号的专属资料，匹配消费者明确条件并说明取舍；资料没提供的限制仍保持未知。
team_fictional须在action和实际回复中明确归属演示资料，不能包装成真实商品效果或医学证据。
已有不适或需要转人工时不得继续推荐试用或护理方案；无关物流咨询不得附加旧护理建议。
主要方案必须在recommended回复中自然体现，不能只在内部数组里有内容。
仅要求比较时，额外清洁/护理建议和重复堆砌资料不算针对性提升，应删除与当前任务无关的话语。
发现以上问题时supported=false，指出具体建议需改动或删除。"""


def validate_care_preferences(texts: list[str], latest_message: str) -> list[str]:
    """Gate only explicit declined care steps; attempted measures need semantic review."""
    declined = set()
    for clause in re.split(r"[，。！？!?；;\n]|但是|不过|但", latest_message):
        if re.search(r"(?:不要|不用|不想|别).{0,18}(?:清洁|保湿)", clause):
            declined.update(step for step in ("清洁", "保湿") if step in clause)
    issues = []
    for text in texts:
        for clause in re.split(r"[，。！？!?；;\n]|但是|不过|但", text):
            for step in declined:
                for action in re.finditer(
                    rf"(?:先|仍|保持|保留|重视|建议|进行|加强|做好|继续).{{0,8}}{step}",
                    clause,
                ):
                    prefix = clause[:action.start()]
                    suffix = clause[action.end():]
                    if re.search(
                        r"不要|不必|无需|不用|不要求|不建议|不再|不提|不会|不能|不等于|不代表|"
                        r"试过|尝试过|已尝试|已经(?:用过|做过|试过|尝试)",
                        prefix,
                    ) or re.match(r"(?:已经|已)?(?:试过|尝试过|用过|做过)", suffix):
                        continue
                    issues.append(
                        f"消费者本轮明确不再要求{step}，删除正文或建议中的重复措施“{action.group()}”；"
                        "保留已试措施的描述，改为有依据的其他筛选条件"
                    )
    return list(dict.fromkeys(issues))


def validate_advice(
    items: list[AdviceCandidate],
    catalog: dict[str, GroundingSource],
    *,
    intent: str,
    handoff_required: bool,
    latest_message: str,
) -> list[str]:
    if not items:
        return []
    if intent != "product_question" or handoff_required:
        return ["当前不是可继续AI接待的美妆咨询，移除personalized_advice，不沿用历史护理建议"]
    refuses_products = bool(re.search(
        r"(?:不要|不想|不需要|不用|别).{0,6}(?:推荐|推).{0,6}(?:品牌|牌子|商品|产品)",
        latest_message,
    ))
    issues = []
    product_identities = product_names(catalog)
    for index, item in enumerate(items, 1):
        prefix = f"第{index}条个性化建议"
        customer, knowledge = False, False
        product_sources = []
        for citation in item.evidence:
            source = catalog.get(citation.source_ref)
            if source is None or citation.quote not in source.text:
                issues.append(f"{prefix}未使用来源逐字原文；从真实sourceId复制连续且相关的quote")
                continue
            customer |= source.kind == "customer_message"
            if source.kind == "knowledge":
                if item.scope == "general_consumer":
                    knowledge |= source.fields.get("scope") == "general_consumer" or GENERAL_KNOWLEDGE_MARKER in source.text
                elif (
                    item.product_sku and source.fields.get("scope") == "product_specific"
                    and source.fields.get("productSku") == item.product_sku
                    and source.fields.get("products") == [item.product_sku]
                    and GENERAL_KNOWLEDGE_MARKER not in source.text
                ):
                    knowledge = True
                    product_sources.append(source)
            if source.kind not in {"customer_message", "knowledge"}:
                issues.append(f"{prefix}必须引用消费者自述和通用知识，不用订单或客服承诺推断肤质")
        if not customer or not knowledge:
            issues.append(f"{prefix}缺少消费者自述或对应范围的知识证据；没有依据时移除，不编造方案")
        if item.scope == "general_consumer" and item.product_sku:
            issues.append(f"{prefix}通用知识不能绑定具体货号，移除货号或引用该货号专属资料")
        if item.scope == "product_specific":
            if not item.claims:
                issues.append(f"{prefix}商品选择须用claims逐项引用商品属性")
            if not item.product_sku or item.product_sku not in mentioned_products(item.action, product_identities):
                issues.append(f"{prefix}商品选择须在action写明主要候选的名称、标识或登记简称")
            if refuses_products:
                issues.append(f"{prefix}当前消费者拒绝具体商品推荐，保留通用选择条件而非货号方案")
            if (
                any(s.fields.get("provenance") == "team_fictional" for s in product_sources)
                and not re.search(r"演示|虚构", item.action)
            ):
                issues.append(f"{prefix}使用团队虚构资料，action必须明确归属演示商品资料")
        if refuses_products and any(
            re.search(r"(?:补充|提供|核对|推荐|选择|购买|选购).{0,8}(?:品牌|牌子|货号|商品名|产品名)", clause)
            and not re.search(r"不要|不必|无需|不用|不要求|不推荐|不推", clause)
            for clause in re.split(r"[，。；;\n]", item.action)
        ):
            issues.append(f"{prefix}与当前不推荐品牌/商品的偏好不符，移除商品推荐与商品资料缺项")
        # Claims must belong to a presentation field, not a fabricated boundary
        # between the action and its reason.
        fields = (item.title, item.action, item.rationale)
        for claim in item.claims:
            if not any(claim.text in text for text in fields):
                issues.append(f"{prefix}claims.text须来自同一action或rationale的连续原文")
        issues.extend(
            f"personalized_advice[{index - 1}]：{issue}"
            for issue in validate_claims(
                "。".join(fields), item.claims, catalog, surface="建议title/action/rationale",
            )
        )
    issues.extend(validate_care_preferences([item.action for item in items], latest_message))
    return list(dict.fromkeys(issues))


def _source_excerpt(source: GroundingSource) -> str:
    url = source.fields.get("sourceUrl")
    if isinstance(url, str) and url and url in source.text:
        body = source.text.partition(url)[2].lstrip()
        if body:
            return body
    return source.text


def _advice_evidence(
    item: AdviceCandidate, catalog: dict[str, GroundingSource],
) -> list[PersonalizedAdviceEvidence]:
    evidence = [
        PersonalizedAdviceEvidence(
            source_ref=citation.source_ref, quote=citation.quote,
            label=catalog[citation.source_ref].label,
            kind=catalog[citation.source_ref].kind,
        )
        for citation in item.evidence
    ]
    seen = {citation.source_ref for citation in evidence}
    for claim in item.claims:
        for ref in claim.source_refs:
            source = catalog.get(ref)
            if ref in seen or source is None or source.kind != "knowledge":
                continue
            evidence.append(PersonalizedAdviceEvidence(
                source_ref=ref, quote=_source_excerpt(source),
                label=source.label, kind=source.kind,
            ))
            seen.add(ref)
    return evidence


def advice_views(
    items: list[AdviceCandidate], catalog: dict[str, GroundingSource],
) -> list[PersonalizedAdviceView]:
    """Render only candidates already accepted by both workflow gates."""
    product_names_by_sku = {
        str(source.fields["productSku"]): str(source.fields["productName"])
        for source in catalog.values()
        if source.kind == "knowledge"
        and source.fields.get("productSku")
        and source.fields.get("productName")
    }
    return [
        PersonalizedAdviceView(
            category=item.category, title=item.title, action=item.action,
            rationale=item.rationale, scope=item.scope, product_sku=item.product_sku,
            product_name=product_names_by_sku.get(item.product_sku) if item.product_sku else None,
            evidence=_advice_evidence(item, catalog),
            claims=item.claims,
        )
        for item in items
    ]
