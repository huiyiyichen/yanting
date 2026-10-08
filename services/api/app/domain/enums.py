"""固定枚举的唯一来源（后端）。

规则（工程规范第 4.2 节）：
- 机器值稳定、英文、snake_case；展示文案与机器值分离；
- 后端拒绝未知值，或对允许的分类字段归为明确的 `unknown`；
- 前端不自行增加业务状态；任何状态变更都记录事件。

本模块是唯一事实来源：`packages/contracts/enums/enums.json` 由脚本从此处导出，
前端 TypeScript 类型由同一份产物生成，不手工维护第二份。
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypeVar

__all__ = [
    "CaseStatus",
    "ComplaintRisk",
    "ConversationStage",
    "CustomerIntent",
    "DealerAuthorizationStatus",
    "EmotionLevel",
    "EmotionTrend",
    "FaultPart",
    "FaultType",
    "KnowledgeHitStatus",
    "KnowledgeSourceType",
    "Locale",
    "PurchaseChannel",
    "RatingStatus",
    "RequestStatus",
    "RequestType",
    "RiskLevel",
    "SenderRole",
    "ServiceMode",
    "ServiceRiskLevel",
    "ServiceRiskStatus",
    "ServiceRiskType",
    "ToolName",
    "ToolResultStatus",
    "TroubleshootingResult",
    "ViewRole",
    "WarrantyStatus",
    "enum_values",
]


class _Base(StrEnum):
    """所有枚举的基类：提供中文展示文案与安全解析。"""

    @property
    def label(self) -> str:
        if type(self) in _LABEL_OVERRIDES:
            return _LABEL_OVERRIDES[type(self)][self.value]
        return _LABELS[self]  # type: ignore[index]

    @classmethod
    def values(cls) -> list[str]:
        return [member.value for member in cls]

    @classmethod
    def parse(cls, raw: object) -> _E:
        """严格解析：非法值直接抛错，不允许静默兜底。

        只有声明包含 UNKNOWN 的枚举，调用方才应显式选择 `parse_or_unknown`。
        """

        if isinstance(raw, cls):
            return raw
        if isinstance(raw, str):
            try:
                return cls(raw)
            except ValueError as exc:
                raise ValueError(
                    f"{cls.__name__} 不接受取值 {raw!r}；合法值：{cls.values()}"
                ) from exc
        raise ValueError(f"{cls.__name__} 需要字符串输入，收到 {type(raw).__name__}")

    @classmethod
    def parse_or_unknown(cls, raw: object) -> _E:
        """仅用于允许 unknown 的分类字段（模型输出可能不可靠）。"""

        if "unknown" not in cls.values():
            raise TypeError(f"{cls.__name__} 未声明 unknown，不能使用 parse_or_unknown")
        try:
            return cls.parse(raw)
        except ValueError:
            return cls("unknown")  # type: ignore[return-value]


_E = TypeVar("_E", bound=_Base)


class CaseStatus(_Base):
    """案件办理状态。`open`/`awaiting_user`/`pending_review`/`closed`。

    注意：`closed` 只表示流程结束，不等于设备修好或业务已履行。
    """

    OPEN = "open"
    AWAITING_USER = "awaiting_user"
    PENDING_REVIEW = "pending_review"
    CLOSED = "closed"


class ConversationStage(_Base):
    """会话当前所处的处理阶段（程序状态，不是渲染视角）。"""

    NEW = "new"
    INTAKE = "intake"
    DISAMBIGUATION = "disambiguation"
    DIAGNOSIS = "diagnosis"
    ELIGIBILITY = "eligibility"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CLOSURE = "closure"
    RATING = "rating"
    CLOSED = "closed"


class RequestType(_Base):
    """售后申请类型。本期只生成草稿，不执行真实业务动作。"""

    REFUND = "refund"
    REPLACEMENT = "replacement"
    REPAIR = "repair"
    PARTS_RESHIPMENT = "parts_reshipment"
    WARRANTY_VERIFICATION = "warranty_verification"
    DEALER_AUTHORIZATION_REVIEW = "dealer_authorization_review"
    OTHER = "other"


class RequestStatus(_Base):
    """申请状态。不包含任何人工超时状态。"""

    DRAFT = "draft"
    PENDING_CONFIRMATION = "pending_confirmation"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_INFORMATION = "needs_information"


class ToolName(_Base):
    """工具白名单。未列出的名称一律拒绝。"""

    KNOWLEDGE_SEARCH = "knowledge_search"
    ORDER_LOOKUP = "order_lookup"
    DEALER_LOOKUP = "dealer_lookup"
    PRODUCT_LOOKUP = "product_lookup"
    WARRANTY_EVALUATE = "warranty_evaluate"
    TROUBLESHOOTING_PLAN = "troubleshooting_plan"
    CREATE_AFTER_SALES_REQUEST = "create_after_sales_request"
    RECORD_CASE_FACT = "record_case_fact"
    RECORD_RATING = "record_rating"


class ToolResultStatus(_Base):
    """工具返回状态。失败、超时、无权限、空结果必须彼此区分。"""

    OK = "ok"
    EMPTY = "empty"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    FAILED = "failed"
    DENIED = "denied"
    INVALID_ARGUMENT = "invalid_argument"
    CONFLICT = "conflict"


class RiskLevel(_Base):
    """动作风险等级。`high_risk` 本期不开放执行。"""

    READ_ONLY = "read_only"
    RECORDING = "recording"
    REQUEST_CREATION = "request_creation"
    HIGH_RISK = "high_risk"


class ServiceRiskType(_Base):
    """消费者服务风险类型。"""

    EMOTION_ESCALATION = "emotion_escalation"
    REPEATED_CONTACT = "repeated_contact"
    REPEATED_REFUND = "repeated_refund"
    ADVERSE_REACTION = "adverse_reaction"
    ABNORMAL_RETURN = "abnormal_return"
    WORK_ORDER_OVERDUE = "work_order_overdue"
    COMPLAINT_RISK = "complaint_risk"
    DATA_CONFLICT = "data_conflict"
    SERVICE_BREAKPOINT = "service_breakpoint"
    RESPONSE_WAIT = "response_wait"
    FOLLOWUP_DUE_SOON = "followup_due_soon"
    UNKNOWN = "unknown"


class ServiceRiskLevel(_Base):
    """消费者服务风险等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class ServiceRiskStatus(_Base):
    """消费者服务风险处理状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class KnowledgeSourceType(_Base):
    """知识源类型。权限由 visibility 决定，不由类型或名称决定。"""

    PRODUCT_KNOWLEDGE = "product_knowledge"
    TROUBLESHOOTING = "troubleshooting"
    SOP = "sop"
    WARRANTY_POLICY = "warranty_policy"


class Visibility(_Base):
    """知识可见范围。客户接口只能返回 customer_visible。"""

    CUSTOMER_VISIBLE = "customer_visible"
    INTERNAL = "internal"


class CustomerIntent(_Base):
    """固定客户意图。允许 unknown，不允许自由文本替代。"""

    DIAGNOSIS = "diagnosis"
    WARRANTY_CHECK = "warranty_check"
    REPAIR = "repair"
    PARTS = "parts"
    REPLACEMENT = "replacement"
    REFUND = "refund"
    COMPLAINT = "complaint"
    PROGRESS_CHECK = "progress_check"
    UNKNOWN = "unknown"


class FaultType(_Base):
    """故障类型固定枚举，无法判断时 unknown。"""

    NO_POWER = "no_power"
    NO_SUCTION = "no_suction"
    WEAK_SUCTION = "weak_suction"
    WATER_LEAK = "water_leak"
    ABNORMAL_NOISE = "abnormal_noise"
    OVERHEATING = "overheating"
    CHARGING_FAILURE = "charging_failure"
    CONNECTIVITY_FAILURE = "connectivity_failure"
    PHYSICAL_DAMAGE = "physical_damage"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    UNKNOWN = "unknown"


class FaultPart(_Base):
    """故障部位固定枚举，无法判断时 unknown。"""

    BODY = "body"
    BATTERY = "battery"
    CHARGING_PORT = "charging_port"
    FILTER = "filter"
    BRUSH = "brush"
    TANK = "tank"
    SEAL = "seal"
    MOTOR = "motor"
    DISPLAY = "display"
    CABLE = "cable"
    ACCESSORY = "accessory"
    UNKNOWN = "unknown"


class EmotionLevel(_Base):
    """情绪等级。只影响沟通策略，不改变质保或赔付规则。"""

    CALM = "calm"
    DISSATISFIED = "dissatisfied"
    ANGRY = "angry"
    UNKNOWN = "unknown"


class EmotionTrend(_Base):
    """消费者消息情绪趋势。"""

    STABLE = "stable"
    RISING = "rising"
    FALLING = "falling"
    REPEATED = "repeated"
    UNKNOWN = "unknown"


class ComplaintRisk(_Base):
    """投诉风险，与情绪分开记录。"""

    FLAGGED = "flagged"
    NOT_FLAGGED = "not_flagged"
    UNKNOWN = "unknown"


class RatingStatus(_Base):
    """满意度环节状态。"""

    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    SUBMITTED = "submitted"
    SKIPPED = "skipped"


class WarrantyStatus(_Base):
    """质保结论。必须区分未知、冲突与查询失败。"""

    IN_WARRANTY = "in_warranty"
    OUT_OF_WARRANTY = "out_of_warranty"
    UNKNOWN = "unknown"
    QUERY_FAILED = "query_failed"
    CONFLICTING = "conflicting"


class DealerAuthorizationStatus(_Base):
    """经销商授权核验结论。相似度本身不证明授权。"""

    AUTHORIZED = "authorized"
    NOT_AUTHORIZED = "not_authorized"
    UNKNOWN = "unknown"
    QUERY_FAILED = "query_failed"
    MULTIPLE_MATCHES = "multiple_matches"
    NOT_APPLICABLE = "not_applicable"


class KnowledgeHitStatus(_Base):
    """知识命中情况。未检索时该字段为空，不用 not_found 代替。"""

    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    NOT_FOUND = "not_found"
    CONFLICTING = "conflicting"


class TroubleshootingResult(_Base):
    """排障结果。只有用户确认才能记为 resolved。"""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    NOT_ATTEMPTED = "not_attempted"
    UNKNOWN = "unknown"


class ServiceMode(_Base):
    """会话服务模式，与页面视角无关。"""

    AUTONOMOUS = "autonomous"
    OPERATOR_ASSISTED = "operator_assisted"


class SenderRole(_Base):
    """消息发送者。渲染方向由 viewRole 计算，数据本身不翻转。"""

    CUSTOMER = "customer"
    ASSISTANT = "assistant"
    OPERATOR = "operator"
    SYSTEM = "system"


class ViewRole(_Base):
    """演示视角。仅用于本机 Demo，不是生产认证。"""

    CUSTOMER = "customer"
    SUPPORT = "support"


class ActorType(_Base):
    """审计事件的操作者类型。"""

    CUSTOMER = "customer"
    AGENT = "agent"
    OPERATOR = "operator"
    SYSTEM = "system"


class PurchaseChannel(_Base):
    """购买渠道固定枚举。"""

    OFFICIAL_WEBSITE = "official_website"
    OFFICIAL_STORE = "official_store"
    MARKETPLACE = "marketplace"
    AUTHORIZED_DEALER = "authorized_dealer"
    THIRD_PARTY_SELLER = "third_party_seller"
    OFFLINE_RETAIL = "offline_retail"
    UNKNOWN = "unknown"


class Locale(_Base):
    """国家/地区标准代码（ISO 3166-1 alpha-2）。"""

    CN = "CN"
    US = "US"
    DE = "DE"
    JP = "JP"
    GB = "GB"
    FR = "FR"
    AU = "AU"
    CA = "CA"


_LABELS: dict[_Base, str] = {
    # CaseStatus
    CaseStatus.OPEN: "办理中",
    CaseStatus.AWAITING_USER: "等待用户补充",
    CaseStatus.PENDING_REVIEW: "待后台确认",
    CaseStatus.CLOSED: "已结束",
    # ConversationStage
    ConversationStage.NEW: "新会话",
    ConversationStage.INTAKE: "信息收集",
    ConversationStage.DISAMBIGUATION: "产品消歧",
    ConversationStage.DIAGNOSIS: "故障诊断",
    ConversationStage.ELIGIBILITY: "资格核验",
    ConversationStage.AWAITING_CONFIRMATION: "等待人工确认",
    ConversationStage.CLOSURE: "办理收尾",
    ConversationStage.RATING: "满意度评价",
    ConversationStage.CLOSED: "已关闭",
    # RequestType
    RequestType.REFUND: "退货退款",
    RequestType.REPLACEMENT: "换货",
    RequestType.REPAIR: "售后维修",
    RequestType.PARTS_RESHIPMENT: "补发配件",
    RequestType.WARRANTY_VERIFICATION: "质保核验",
    RequestType.DEALER_AUTHORIZATION_REVIEW: "经销商授权复核",
    RequestType.OTHER: "其他申请",
    # RequestStatus
    RequestStatus.DRAFT: "草稿",
    RequestStatus.PENDING_CONFIRMATION: "待人工确认",
    RequestStatus.APPROVED: "已批准",
    RequestStatus.REJECTED: "已拒绝",
    RequestStatus.NEEDS_INFORMATION: "退回补充",
    # ToolName
    ToolName.KNOWLEDGE_SEARCH: "知识检索",
    ToolName.ORDER_LOOKUP: "订单查询",
    ToolName.DEALER_LOOKUP: "经销商核验",
    ToolName.PRODUCT_LOOKUP: "产品查询",
    ToolName.WARRANTY_EVALUATE: "质保判定",
    ToolName.TROUBLESHOOTING_PLAN: "排障方案",
    ToolName.CREATE_AFTER_SALES_REQUEST: "生成申请草稿",
    ToolName.RECORD_CASE_FACT: "记录案件事实",
    ToolName.RECORD_RATING: "记录满意度",
    # ToolResultStatus
    ToolResultStatus.OK: "成功",
    ToolResultStatus.EMPTY: "空结果",
    ToolResultStatus.NOT_FOUND: "未命中",
    ToolResultStatus.TIMEOUT: "超时",
    ToolResultStatus.FAILED: "执行失败",
    ToolResultStatus.DENIED: "无权限",
    ToolResultStatus.INVALID_ARGUMENT: "参数非法",
    ToolResultStatus.CONFLICT: "结果冲突",
    # RiskLevel
    RiskLevel.READ_ONLY: "只读",
    RiskLevel.RECORDING: "记录",
    RiskLevel.REQUEST_CREATION: "生成申请",
    RiskLevel.HIGH_RISK: "高风险",
    # ServiceRiskType
    ServiceRiskType.EMOTION_ESCALATION: "情绪升级",
    ServiceRiskType.REPEATED_CONTACT: "重复进线",
    ServiceRiskType.REPEATED_REFUND: "重复退款",
    ServiceRiskType.ADVERSE_REACTION: "不良反应",
    ServiceRiskType.ABNORMAL_RETURN: "异常退货",
    ServiceRiskType.WORK_ORDER_OVERDUE: "工单逾期",
    ServiceRiskType.COMPLAINT_RISK: "投诉风险",
    ServiceRiskType.DATA_CONFLICT: "数据冲突",
    ServiceRiskType.SERVICE_BREAKPOINT: "服务断点",
    ServiceRiskType.RESPONSE_WAIT: "未回复预警",
    ServiceRiskType.FOLLOWUP_DUE_SOON: "跟进临近截止",
    ServiceRiskType.UNKNOWN: "未知",
    # ServiceRiskLevel
    ServiceRiskLevel.LOW: "低",
    ServiceRiskLevel.MEDIUM: "中",
    ServiceRiskLevel.HIGH: "高",
    ServiceRiskLevel.UNKNOWN: "未知",
    # ServiceRiskStatus
    ServiceRiskStatus.PENDING: "待处理",
    ServiceRiskStatus.IN_PROGRESS: "处理中",
    ServiceRiskStatus.RESOLVED: "已处理",
    ServiceRiskStatus.IGNORED: "已忽略",
    # KnowledgeSourceType
    KnowledgeSourceType.PRODUCT_KNOWLEDGE: "产品资料",
    KnowledgeSourceType.TROUBLESHOOTING: "排障资料",
    KnowledgeSourceType.SOP: "业务 SOP",
    KnowledgeSourceType.WARRANTY_POLICY: "质保政策",
    # Visibility
    Visibility.CUSTOMER_VISIBLE: "客户可见",
    Visibility.INTERNAL: "内部可见",
    # CustomerIntent
    CustomerIntent.DIAGNOSIS: "故障诊断",
    CustomerIntent.WARRANTY_CHECK: "质保查询",
    CustomerIntent.REPAIR: "维修",
    CustomerIntent.PARTS: "补件",
    CustomerIntent.REPLACEMENT: "换货",
    CustomerIntent.REFUND: "退款",
    CustomerIntent.COMPLAINT: "投诉",
    CustomerIntent.PROGRESS_CHECK: "进度查询",
    CustomerIntent.UNKNOWN: "未知",
    # FaultType
    FaultType.NO_POWER: "无法开机",
    FaultType.NO_SUCTION: "无吸力",
    FaultType.WEAK_SUCTION: "吸力减弱",
    FaultType.WATER_LEAK: "漏水",
    FaultType.ABNORMAL_NOISE: "异响",
    FaultType.OVERHEATING: "过热",
    FaultType.CHARGING_FAILURE: "无法充电",
    FaultType.CONNECTIVITY_FAILURE: "无法连接",
    FaultType.PHYSICAL_DAMAGE: "外观破损",
    FaultType.PERFORMANCE_DEGRADATION: "性能下降",
    FaultType.UNKNOWN: "未知",
    # FaultPart
    FaultPart.BODY: "机身",
    FaultPart.BATTERY: "电池",
    FaultPart.CHARGING_PORT: "充电口",
    FaultPart.FILTER: "滤网",
    FaultPart.BRUSH: "刷头",
    FaultPart.TANK: "水箱",
    FaultPart.SEAL: "密封件",
    FaultPart.MOTOR: "电机",
    FaultPart.DISPLAY: "显示面板",
    FaultPart.CABLE: "线材",
    FaultPart.ACCESSORY: "配件",
    FaultPart.UNKNOWN: "未知",
    # EmotionLevel
    EmotionLevel.CALM: "平稳",
    EmotionLevel.DISSATISFIED: "不满",
    EmotionLevel.ANGRY: "愤怒",
    EmotionLevel.UNKNOWN: "未知",
    # EmotionTrend
    EmotionTrend.STABLE: "平稳",
    EmotionTrend.RISING: "升高",
    EmotionTrend.FALLING: "下降",
    EmotionTrend.REPEATED: "反复",
    EmotionTrend.UNKNOWN: "未知",
    # ComplaintRisk
    ComplaintRisk.FLAGGED: "有投诉风险",
    ComplaintRisk.NOT_FLAGGED: "无投诉风险",
    ComplaintRisk.UNKNOWN: "未知",
    # RatingStatus
    RatingStatus.NOT_REQUESTED: "未开始",
    RatingStatus.PENDING: "待评价",
    RatingStatus.SUBMITTED: "已评价",
    RatingStatus.SKIPPED: "已跳过",
    # WarrantyStatus
    WarrantyStatus.IN_WARRANTY: "保修期内",
    WarrantyStatus.OUT_OF_WARRANTY: "已过保",
    WarrantyStatus.UNKNOWN: "无法判断",
    WarrantyStatus.QUERY_FAILED: "查询失败",
    WarrantyStatus.CONFLICTING: "信息冲突",
    # DealerAuthorizationStatus
    DealerAuthorizationStatus.AUTHORIZED: "已核验授权",
    DealerAuthorizationStatus.NOT_AUTHORIZED: "非授权渠道",
    DealerAuthorizationStatus.UNKNOWN: "无法判断",
    DealerAuthorizationStatus.QUERY_FAILED: "查询失败",
    DealerAuthorizationStatus.MULTIPLE_MATCHES: "多个匹配",
    DealerAuthorizationStatus.NOT_APPLICABLE: "不适用",
    # KnowledgeHitStatus
    KnowledgeHitStatus.SUFFICIENT: "命中充分",
    KnowledgeHitStatus.INSUFFICIENT: "命中不足",
    KnowledgeHitStatus.NOT_FOUND: "未命中",
    KnowledgeHitStatus.CONFLICTING: "依据冲突",
    # TroubleshootingResult
    TroubleshootingResult.RESOLVED: "用户确认解决",
    TroubleshootingResult.UNRESOLVED: "未解决",
    TroubleshootingResult.NOT_ATTEMPTED: "未尝试",
    TroubleshootingResult.UNKNOWN: "未知",
    # ServiceMode
    ServiceMode.AUTONOMOUS: "AI 托管",
    ServiceMode.OPERATOR_ASSISTED: "客服接管",
    # SenderRole
    SenderRole.CUSTOMER: "客户",
    SenderRole.ASSISTANT: "智能助手",
    SenderRole.OPERATOR: "客服",
    SenderRole.SYSTEM: "系统通知",
    # ViewRole
    ViewRole.CUSTOMER: "客户视角",
    ViewRole.SUPPORT: "客服工作台",
    # ActorType
    ActorType.CUSTOMER: "客户",
    ActorType.AGENT: "Agent",
    ActorType.OPERATOR: "客服",
    ActorType.SYSTEM: "系统",
    # PurchaseChannel
    PurchaseChannel.OFFICIAL_WEBSITE: "品牌官网",
    PurchaseChannel.OFFICIAL_STORE: "品牌官方店",
    PurchaseChannel.MARKETPLACE: "电商平台",
    PurchaseChannel.AUTHORIZED_DEALER: "授权经销商",
    PurchaseChannel.THIRD_PARTY_SELLER: "第三方卖家",
    PurchaseChannel.OFFLINE_RETAIL: "线下零售",
    PurchaseChannel.UNKNOWN: "未知",
    # Locale
    Locale.CN: "中国大陆",
    Locale.US: "美国",
    Locale.DE: "德国",
    Locale.JP: "日本",
    Locale.GB: "英国",
    Locale.FR: "法国",
    Locale.AU: "澳大利亚",
    Locale.CA: "加拿大",
}


_LABEL_OVERRIDES = {
    ServiceRiskStatus: {
        "pending": "待处理",
        "in_progress": "处理中",
        "resolved": "已处理",
        "ignored": "已忽略",
    },
}


def enum_values() -> dict[str, dict[str, str]]:
    """导出全部枚举及其展示文案，供契约产物与前端类型生成使用。"""

    registry: dict[str, type[_Base]] = {
        "caseStatus": CaseStatus,
        "conversationStage": ConversationStage,
        "requestType": RequestType,
        "requestStatus": RequestStatus,
        "toolName": ToolName,
        "toolResultStatus": ToolResultStatus,
        "riskLevel": RiskLevel,
        "serviceRiskType": ServiceRiskType,
        "serviceRiskLevel": ServiceRiskLevel,
        "serviceRiskStatus": ServiceRiskStatus,
        "knowledgeSourceType": KnowledgeSourceType,
        "visibility": Visibility,
        "customerIntent": CustomerIntent,
        "faultType": FaultType,
        "faultPart": FaultPart,
        "emotionLevel": EmotionLevel,
        "emotionTrend": EmotionTrend,
        "complaintRisk": ComplaintRisk,
        "ratingStatus": RatingStatus,
        "warrantyStatus": WarrantyStatus,
        "dealerAuthorizationStatus": DealerAuthorizationStatus,
        "knowledgeHitStatus": KnowledgeHitStatus,
        "troubleshootingResult": TroubleshootingResult,
        "serviceMode": ServiceMode,
        "senderRole": SenderRole,
        "viewRole": ViewRole,
        "actorType": ActorType,
        "purchaseChannel": PurchaseChannel,
        "locale": Locale,
    }
    return {
        name: {member.value: member.label for member in enum_cls}
        for name, enum_cls in registry.items()
    }
