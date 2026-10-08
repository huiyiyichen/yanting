"""理解与分流分析器：把用户表达归一化为固定字段。

设计原则（PRD 第 4.5 节、工程规范第 4.1 节）：
- 模型只**选择固定枚举**或输出未知，不允许自由文本替代未知；
- 模型输出必须经 Pydantic 校验与业务规则校验，校验失败不得猜测修复；
- 情绪只影响沟通策略，**不改变**质保或赔付规则；
- 图片只能提取可见现象，不得推断内部根因；
- 模型不可用时如实暴露错误，不静默回退为预设回复。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.agent.contracts import CaseFacts
from app.domain.enums import (
    ComplaintRisk,
    CustomerIntent,
    EmotionLevel,
    FaultPart,
    FaultType,
    PurchaseChannel,
)
from app.errors import ModelOutputInvalid, ProviderNotConfigured
from app.integrations.model_provider import ChatMessage, ModelProvider
from app.logging_setup import get_logger, log_event

logger = get_logger(__name__)

PROMPT_VERSION = "s2-understanding-v1"

SYSTEM_PROMPT = """你是安克售后服务的理解模块。你的唯一任务是把用户的话转成结构化事实。

严格规则：
1. 只输出 JSON，不要任何解释文字、不要 markdown 代码块。
2. 枚举字段只能取给定取值之一；无法判断时必须填 "unknown"，不要编造。
3. 图片只能证明「可见现象」（如外观破损、水渍、指示灯状态）。
   不得从图片推断内部故障根因，也不得断言是设计或质量问题。
4. 不要承诺质保、退款、赔偿，不要给出金额或时限。这些由后续流程决定。
5. `phenomenon` 用一句中文复述用户描述的现象，不要添加用户没说的信息。

可用枚举：
- fault_type: no_power, no_suction, weak_suction, water_leak, abnormal_noise,
  overheating, charging_failure, connectivity_failure, physical_damage,
  performance_degradation, unknown
- fault_part: body, battery, charging_port, filter, brush, tank, seal, motor,
  display, cable, accessory, unknown
- intents: diagnosis, warranty_check, repair, parts, replacement, refund,
  complaint, progress_check, unknown
- emotion_level: calm, dissatisfied, angry, unknown
- complaint_risk: flagged, not_flagged, unknown
- purchase_channel: official_website, official_store, marketplace,
  authorized_dealer, third_party_seller, offline_retail, unknown

输出 JSON 结构：
{
  "product_model_text": "用户提到的产品名称原文或空字符串",
  "fault_type": "...",
  "fault_part": "...",
  "phenomenon": "...",
  "intents": ["..."],
  "emotion_level": "...",
  "complaint_risk": "...",
  "complaint_reason": "若有投诉风险的简短原因，否则空字符串",
  "country_code_text": "用户提到的国家/地区原文或空字符串",
  "purchase_channel": "...",
  "seller_name_raw": "用户提到的卖家原文或空字符串",
  "image_visible_clues": ["从图片可确认的可见现象，没有则空数组"],
  "urgency_note": "用户表达的紧急程度，没有则空字符串"
}"""


class _Understanding(BaseModel):
    """模型输出的结构契约。`extra="ignore"`：模型多给字段不算错误，但不能少关键字段。"""

    model_config = ConfigDict(extra="ignore")

    product_model_text: str = ""
    fault_type: str = "unknown"
    fault_part: str = "unknown"
    phenomenon: str = ""
    intents: list[str] = Field(default_factory=list)
    emotion_level: str = "unknown"
    complaint_risk: str = "unknown"
    complaint_reason: str = ""
    country_code_text: str = ""
    purchase_channel: str = "unknown"
    seller_name_raw: str = ""
    image_visible_clues: list[str] = Field(default_factory=list)
    urgency_note: str = ""


@dataclass(frozen=True, slots=True)
class Understanding:
    """校验后的理解结果。"""

    facts: CaseFacts
    intents: list[CustomerIntent]
    emotion_level: EmotionLevel
    complaint_risk: ComplaintRisk
    complaint_reason: str
    product_model_text: str
    country_code_text: str
    urgency_note: str
    is_mock: bool
    model_id: str
    latency_seconds: float
    uncertainty_flags: list[str]


# 简单的国家/地区文本映射：真实系统应使用标准地区库，这里只覆盖夹具范围
COUNTRY_TEXT_MAP: dict[str, str] = {
    "中国": "CN",
    "中国大陆": "CN",
    "大陆": "CN",
    "国内": "CN",
    "china": "CN",
    "cn": "CN",
    "美国": "US",
    "美利坚": "US",
    "usa": "US",
    "us": "US",
    "德国": "DE",
    "germany": "DE",
    "de": "DE",
    "日本": "JP",
    "japan": "JP",
    "jp": "JP",
    "英国": "GB",
    "uk": "GB",
    "法国": "FR",
    "澳大利亚": "AU",
}

JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def extract_json(text: str) -> dict[str, Any]:
    """从模型回复中提取 JSON 对象。

    只接受一个 JSON 对象；解析失败必须报错，不做「尽力修复」，
    因为静默修复会把非法输出变成看似合法的业务结论。
    """

    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        match = JSON_BLOCK_RE.search(candidate)
        if not match:
            raise ModelOutputInvalid("模型输出中找不到 JSON 对象", detail=text[:300]) from None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ModelOutputInvalid(
                "模型输出的 JSON 无法解析", detail=f"{exc}: {text[:300]}"
            ) from exc
    if not isinstance(parsed, dict):
        raise ModelOutputInvalid(
            "模型输出必须是 JSON 对象", detail=f"实际类型：{type(parsed).__name__}"
        )
    return parsed


def resolve_country(text: str) -> str | None:
    if not text:
        return None
    normalized = text.strip().lower()
    for key, code in COUNTRY_TEXT_MAP.items():
        if key in normalized:
            return code
    upper = text.strip().upper()
    # 只接受 ASCII 双字母代码：中文「火星」这类两字词也满足 str.isalpha()，
    # 若不限定 ASCII 会被误当成 ISO 3166-1 国家代码。
    if len(upper) == 2 and upper.isascii() and upper.isalpha():
        return upper
    return None


class UnderstandingAnalyzer:
    """把用户文本（与图片线索）转成结构化事实与分流信号。"""

    def __init__(
        self,
        provider: ModelProvider,
        prompt_resolver: Callable[[], str | None] | None = None,
    ) -> None:
        """`prompt_resolver` 返回当前**启用中**的系统提示词（没有则返回 None）。

        由运行时注入：从 `prompt_template` 表里按 code 取启用的那条。
        取不到时回退到本模块的 `SYSTEM_PROMPT` 常量——这样停用模板不会打断链路。
        """
        self._provider = provider
        self._prompt_resolver = prompt_resolver

    def system_prompt(self) -> str:
        """当前使用的系统提示词：优先库里启用中的模板，其次代码常量。"""

        if self._prompt_resolver is not None:
            resolved = self._prompt_resolver()
            if resolved and resolved.strip():
                return resolved
        return SYSTEM_PROMPT

    def analyze(
        self,
        *,
        message: str,
        image_data_urls: list[str] | None = None,
        confirmed_facts: CaseFacts | None = None,
        history: list[str] | None = None,
    ) -> Understanding:
        images = image_data_urls or []
        if images and not self._provider.supports_vision:
            # 明确报错，不假装看懂了图片
            raise ProviderNotConfigured(
                "多模态模型未配置，无法从图片提取线索",
                detail=(
                    "请在配置中设置 ANKER_AGENT_LLM_VISION_MODEL；"
                    "在此之前图片线索提取不可用，也不要把它当作已完成"
                ),
            )

        context_lines: list[str] = []
        if confirmed_facts is not None:
            context_lines.append(
                "已确认事实：" + json.dumps(confirmed_facts.to_dict(), ensure_ascii=False)
            )
        if history:
            context_lines.append("最近对话：" + " | ".join(history[-5:]))
        context_lines.append(f"用户当前消息：{message}")
        prompt = "\n".join(context_lines)

        result = self._provider.complete(
            [
                ChatMessage(role="system", content=self.system_prompt()),
                ChatMessage(role="user", content=prompt, image_data_urls=images),
            ],
            temperature=0.0,
            max_tokens=900,
            json_mode=True,
        )
        payload = extract_json(result.text)
        try:
            parsed = _Understanding.model_validate(payload)
        except ValidationError as exc:
            raise ModelOutputInvalid(
                "模型输出不符合理解模块的结构契约", detail=str(exc)[:600]
            ) from exc

        facts = confirmed_facts or CaseFacts()
        uncertainty: list[str] = []

        model_text = parsed.product_model_text.strip()
        if model_text and not facts.product_model:
            facts.product_model = model_text

        facts.fault_type = FaultType.parse_or_unknown(parsed.fault_type)
        facts.fault_part = FaultPart.parse_or_unknown(parsed.fault_part)
        if parsed.phenomenon.strip():
            facts.phenomenon = parsed.phenomenon.strip()[:500]

        country_text = parsed.country_code_text.strip()
        if not facts.country_code:
            resolved_country = resolve_country(country_text)
            if resolved_country:
                facts.country_code = resolved_country
            elif country_text:
                uncertainty.append("country_unrecognized")

        if parsed.purchase_channel and not facts.purchase_channel:
            try:
                channel = PurchaseChannel(parsed.purchase_channel)
                if channel is not PurchaseChannel.UNKNOWN:
                    facts.purchase_channel = channel.value
            except ValueError:
                uncertainty.append("purchase_channel_unrecognized")

        if parsed.seller_name_raw.strip() and not facts.seller_name_raw:
            facts.seller_name_raw = parsed.seller_name_raw.strip()[:200]

        # 图片线索只作为「可见现象」，不进入 fault_type 的根因判断
        clues = [item.strip()[:200] for item in parsed.image_visible_clues if item.strip()]
        facts.observed_from_image = clues

        intents = _resolve_intents(parsed.intents, message)
        emotion = EmotionLevel.parse_or_unknown(parsed.emotion_level)
        complaint = ComplaintRisk.parse_or_unknown(parsed.complaint_risk)

        if facts.fault_type is FaultType.UNKNOWN and not clues:
            uncertainty.append("fault_type_unknown")

        log_event(
            logger,
            "understanding_done",
            intents=[item.value for item in intents],
            emotion=emotion.value,
            complaint_risk=complaint.value,
            is_mock=result.is_mock,
            latency_seconds=round(result.latency_seconds, 3),
        )

        return Understanding(
            facts=facts,
            intents=intents,
            emotion_level=emotion,
            complaint_risk=complaint,
            complaint_reason=parsed.complaint_reason.strip()[:300],
            product_model_text=model_text,
            country_code_text=country_text,
            urgency_note=parsed.urgency_note.strip()[:200],
            is_mock=result.is_mock,
            model_id=result.model,
            latency_seconds=result.latency_seconds,
            uncertainty_flags=uncertainty,
        )


# 关键词兜底：模型偶尔漏掉明显意图时补齐固定选项（只做加法，不覆盖模型结论）
_INTENT_KEYWORDS: list[tuple[CustomerIntent, tuple[str, ...]]] = [
    (CustomerIntent.REFUND, ("退款", "退钱", "退掉", "退货", "不要了", "退")),
    (CustomerIntent.REPLACEMENT, ("换货", "换新", "换一台", "换一个")),
    (CustomerIntent.REPAIR, ("维修", "报修", "修理", "寄修")),
    (CustomerIntent.PARTS, ("配件", "补件", "滤芯", "滤网", "刷头", "补发")),
    (CustomerIntent.COMPLAINT, ("投诉", "曝光", "监管", "315", "工商", "起诉")),
    (CustomerIntent.WARRANTY_CHECK, ("质保", "保修", "三包", "保内", "保外")),
    (CustomerIntent.PROGRESS_CHECK, ("进度", "到哪了", "什么时候", "催")),
    (CustomerIntent.DIAGNOSIS, ("故障", "不吸", "吸力", "漏水", "开机", "异响", "排查")),
]


def _resolve_intents(raw_intents: list[str], message: str) -> list[CustomerIntent]:
    """归一化意图：模型结论 + 关键词补齐，去重且保持稳定顺序。"""

    resolved: list[CustomerIntent] = []
    for item in raw_intents:
        try:
            intent = CustomerIntent(str(item))
        except ValueError:
            continue
        if intent is not CustomerIntent.UNKNOWN and intent not in resolved:
            resolved.append(intent)

    for intent, keywords in _INTENT_KEYWORDS:
        if intent in resolved:
            continue
        if any(keyword in message for keyword in keywords):
            resolved.append(intent)

    if not resolved:
        resolved.append(CustomerIntent.UNKNOWN)
    return resolved
