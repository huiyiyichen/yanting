/**
 * 本文件由 scripts/generateContracts.mjs 从后端枚举导出自动生成，请勿手工修改。
 * 机器值唯一来源：services/api/app/domain/enums.py
 */

export const CASE_STATUS_VALUES = [
  'open',
  'awaiting_user',
  'pending_review',
  'closed',
] as const

export type CaseStatus = (typeof CASE_STATUS_VALUES)[number]

export const caseStatusLabels: Record<CaseStatus, string> = {
  "open": "办理中",
  "awaiting_user": "等待用户补充",
  "pending_review": "待后台确认",
  "closed": "已关闭"
}

export const CONVERSATION_STAGE_VALUES = [
  'new',
  'intake',
  'disambiguation',
  'diagnosis',
  'eligibility',
  'awaiting_confirmation',
  'closure',
  'rating',
  'closed',
] as const

export type ConversationStage = (typeof CONVERSATION_STAGE_VALUES)[number]

export const conversationStageLabels: Record<ConversationStage, string> = {
  "new": "新会话",
  "intake": "信息收集",
  "disambiguation": "产品消歧",
  "diagnosis": "故障诊断",
  "eligibility": "资格核验",
  "awaiting_confirmation": "等待人工确认",
  "closure": "办理收尾",
  "rating": "满意度评价",
  "closed": "已关闭"
}

export const REQUEST_TYPE_VALUES = [
  'refund',
  'replacement',
  'repair',
  'parts_reshipment',
  'warranty_verification',
  'dealer_authorization_review',
  'other',
] as const

export type RequestType = (typeof REQUEST_TYPE_VALUES)[number]

export const requestTypeLabels: Record<RequestType, string> = {
  "refund": "退款",
  "replacement": "换货",
  "repair": "维修",
  "parts_reshipment": "补发配件",
  "warranty_verification": "质保核验",
  "dealer_authorization_review": "经销商授权复核",
  "other": "其他申请"
}

export const REQUEST_STATUS_VALUES = [
  'draft',
  'pending_confirmation',
  'approved',
  'rejected',
  'needs_information',
] as const

export type RequestStatus = (typeof REQUEST_STATUS_VALUES)[number]

export const requestStatusLabels: Record<RequestStatus, string> = {
  "draft": "草稿",
  "pending_confirmation": "待人工确认",
  "approved": "已批准",
  "rejected": "已拒绝",
  "needs_information": "退回补充"
}

export const TOOL_NAME_VALUES = [
  'knowledge_search',
  'order_lookup',
  'dealer_lookup',
  'product_lookup',
  'warranty_evaluate',
  'troubleshooting_plan',
  'create_after_sales_request',
  'record_case_fact',
  'record_rating',
] as const

export type ToolName = (typeof TOOL_NAME_VALUES)[number]

export const toolNameLabels: Record<ToolName, string> = {
  "knowledge_search": "知识检索",
  "order_lookup": "订单查询",
  "dealer_lookup": "经销商核验",
  "product_lookup": "产品查询",
  "warranty_evaluate": "质保判定",
  "troubleshooting_plan": "排障方案",
  "create_after_sales_request": "生成申请草稿",
  "record_case_fact": "记录案件事实",
  "record_rating": "记录满意度"
}

export const TOOL_RESULT_STATUS_VALUES = [
  'ok',
  'empty',
  'not_found',
  'timeout',
  'failed',
  'denied',
  'invalid_argument',
  'conflict',
] as const

export type ToolResultStatus = (typeof TOOL_RESULT_STATUS_VALUES)[number]

export const toolResultStatusLabels: Record<ToolResultStatus, string> = {
  "ok": "成功",
  "empty": "空结果",
  "not_found": "未命中",
  "timeout": "超时",
  "failed": "执行失败",
  "denied": "无权限",
  "invalid_argument": "参数非法",
  "conflict": "结果冲突"
}

export const RISK_LEVEL_VALUES = [
  'read_only',
  'recording',
  'request_creation',
  'high_risk',
] as const

export type RiskLevel = (typeof RISK_LEVEL_VALUES)[number]

export const riskLevelLabels: Record<RiskLevel, string> = {
  "read_only": "只读",
  "recording": "记录",
  "request_creation": "生成申请",
  "high_risk": "高风险"
}

export const SERVICE_RISK_TYPE_VALUES = [
  'emotion_escalation',
  'repeated_contact',
  'repeated_refund',
  'adverse_reaction',
  'abnormal_return',
  'work_order_overdue',
  'complaint_risk',
  'data_conflict',
  'service_breakpoint',
  'response_wait',
  'followup_due_soon',
  'unknown',
] as const

export type ServiceRiskType = (typeof SERVICE_RISK_TYPE_VALUES)[number]

export const serviceRiskTypeLabels: Record<ServiceRiskType, string> = {
  "emotion_escalation": "情绪升级",
  "repeated_contact": "重复进线",
  "repeated_refund": "重复退款",
  "adverse_reaction": "不良反应",
  "abnormal_return": "异常退货",
  "work_order_overdue": "工单逾期",
  "complaint_risk": "投诉风险",
  "data_conflict": "数据冲突",
  "service_breakpoint": "服务断点",
  "response_wait": "未回复预警",
  "followup_due_soon": "跟进临近截止",
  "unknown": "未知"
}

export const SERVICE_RISK_LEVEL_VALUES = [
  'low',
  'medium',
  'high',
  'unknown',
] as const

export type ServiceRiskLevel = (typeof SERVICE_RISK_LEVEL_VALUES)[number]

export const serviceRiskLevelLabels: Record<ServiceRiskLevel, string> = {
  "low": "低",
  "medium": "中",
  "high": "高",
  "unknown": "未知"
}

export const SERVICE_RISK_STATUS_VALUES = [
  'pending',
  'in_progress',
  'resolved',
  'ignored',
] as const

export type ServiceRiskStatus = (typeof SERVICE_RISK_STATUS_VALUES)[number]

export const serviceRiskStatusLabels: Record<ServiceRiskStatus, string> = {
  "pending": "待处理",
  "in_progress": "处理中",
  "resolved": "已处理",
  "ignored": "已忽略"
}

export const KNOWLEDGE_SOURCE_TYPE_VALUES = [
  'product_knowledge',
  'troubleshooting',
  'sop',
  'warranty_policy',
] as const

export type KnowledgeSourceType = (typeof KNOWLEDGE_SOURCE_TYPE_VALUES)[number]

export const knowledgeSourceTypeLabels: Record<KnowledgeSourceType, string> = {
  "product_knowledge": "产品资料",
  "troubleshooting": "排障资料",
  "sop": "业务 SOP",
  "warranty_policy": "质保政策"
}

export const VISIBILITY_VALUES = [
  'customer_visible',
  'internal',
] as const

export type Visibility = (typeof VISIBILITY_VALUES)[number]

export const visibilityLabels: Record<Visibility, string> = {
  "customer_visible": "客户可见",
  "internal": "内部可见"
}

export const CUSTOMER_INTENT_VALUES = [
  'diagnosis',
  'warranty_check',
  'repair',
  'parts',
  'replacement',
  'refund',
  'complaint',
  'progress_check',
  'unknown',
] as const

export type CustomerIntent = (typeof CUSTOMER_INTENT_VALUES)[number]

export const customerIntentLabels: Record<CustomerIntent, string> = {
  "diagnosis": "故障诊断",
  "warranty_check": "质保查询",
  "repair": "维修",
  "parts": "补件",
  "replacement": "换货",
  "refund": "退款",
  "complaint": "投诉",
  "progress_check": "进度查询",
  "unknown": "未知"
}

export const FAULT_TYPE_VALUES = [
  'no_power',
  'no_suction',
  'weak_suction',
  'water_leak',
  'abnormal_noise',
  'overheating',
  'charging_failure',
  'connectivity_failure',
  'physical_damage',
  'performance_degradation',
  'unknown',
] as const

export type FaultType = (typeof FAULT_TYPE_VALUES)[number]

export const faultTypeLabels: Record<FaultType, string> = {
  "no_power": "无法开机",
  "no_suction": "无吸力",
  "weak_suction": "吸力减弱",
  "water_leak": "漏水",
  "abnormal_noise": "异响",
  "overheating": "过热",
  "charging_failure": "无法充电",
  "connectivity_failure": "无法连接",
  "physical_damage": "外观破损",
  "performance_degradation": "性能下降",
  "unknown": "未知"
}

export const FAULT_PART_VALUES = [
  'body',
  'battery',
  'charging_port',
  'filter',
  'brush',
  'tank',
  'seal',
  'motor',
  'display',
  'cable',
  'accessory',
  'unknown',
] as const

export type FaultPart = (typeof FAULT_PART_VALUES)[number]

export const faultPartLabels: Record<FaultPart, string> = {
  "body": "机身",
  "battery": "电池",
  "charging_port": "充电口",
  "filter": "滤网",
  "brush": "刷头",
  "tank": "水箱",
  "seal": "密封件",
  "motor": "电机",
  "display": "显示面板",
  "cable": "线材",
  "accessory": "配件",
  "unknown": "未知"
}

export const EMOTION_LEVEL_VALUES = [
  'calm',
  'dissatisfied',
  'angry',
  'unknown',
] as const

export type EmotionLevel = (typeof EMOTION_LEVEL_VALUES)[number]

export const emotionLevelLabels: Record<EmotionLevel, string> = {
  "calm": "平稳",
  "dissatisfied": "不满",
  "angry": "愤怒",
  "unknown": "未知"
}

export const EMOTION_TREND_VALUES = [
  'stable',
  'rising',
  'falling',
  'repeated',
  'unknown',
] as const

export type EmotionTrend = (typeof EMOTION_TREND_VALUES)[number]

export const emotionTrendLabels: Record<EmotionTrend, string> = {
  "stable": "平稳",
  "rising": "升高",
  "falling": "下降",
  "repeated": "反复",
  "unknown": "未知"
}

export const COMPLAINT_RISK_VALUES = [
  'flagged',
  'not_flagged',
  'unknown',
] as const

export type ComplaintRisk = (typeof COMPLAINT_RISK_VALUES)[number]

export const complaintRiskLabels: Record<ComplaintRisk, string> = {
  "flagged": "有投诉风险",
  "not_flagged": "无投诉风险",
  "unknown": "未知"
}

export const RATING_STATUS_VALUES = [
  'not_requested',
  'pending',
  'submitted',
  'skipped',
] as const

export type RatingStatus = (typeof RATING_STATUS_VALUES)[number]

export const ratingStatusLabels: Record<RatingStatus, string> = {
  "not_requested": "未开始",
  "pending": "待评价",
  "submitted": "已评价",
  "skipped": "已跳过"
}

export const WARRANTY_STATUS_VALUES = [
  'in_warranty',
  'out_of_warranty',
  'unknown',
  'query_failed',
  'conflicting',
] as const

export type WarrantyStatus = (typeof WARRANTY_STATUS_VALUES)[number]

export const warrantyStatusLabels: Record<WarrantyStatus, string> = {
  "in_warranty": "保修期内",
  "out_of_warranty": "已过保",
  "unknown": "未知",
  "query_failed": "查询失败",
  "conflicting": "依据冲突"
}

export const DEALER_AUTHORIZATION_STATUS_VALUES = [
  'authorized',
  'not_authorized',
  'unknown',
  'query_failed',
  'multiple_matches',
  'not_applicable',
] as const

export type DealerAuthorizationStatus = (typeof DEALER_AUTHORIZATION_STATUS_VALUES)[number]

export const dealerAuthorizationStatusLabels: Record<DealerAuthorizationStatus, string> = {
  "authorized": "已核验授权",
  "not_authorized": "非授权渠道",
  "unknown": "未知",
  "query_failed": "查询失败",
  "multiple_matches": "多个匹配",
  "not_applicable": "不适用"
}

export const KNOWLEDGE_HIT_STATUS_VALUES = [
  'sufficient',
  'insufficient',
  'not_found',
  'conflicting',
] as const

export type KnowledgeHitStatus = (typeof KNOWLEDGE_HIT_STATUS_VALUES)[number]

export const knowledgeHitStatusLabels: Record<KnowledgeHitStatus, string> = {
  "sufficient": "命中充分",
  "insufficient": "命中不足",
  "not_found": "未命中",
  "conflicting": "依据冲突"
}

export const TROUBLESHOOTING_RESULT_VALUES = [
  'resolved',
  'unresolved',
  'not_attempted',
  'unknown',
] as const

export type TroubleshootingResult = (typeof TROUBLESHOOTING_RESULT_VALUES)[number]

export const troubleshootingResultLabels: Record<TroubleshootingResult, string> = {
  "resolved": "用户确认解决",
  "unresolved": "未解决",
  "not_attempted": "未尝试",
  "unknown": "未知"
}

export const SERVICE_MODE_VALUES = [
  'autonomous',
  'operator_assisted',
] as const

export type ServiceMode = (typeof SERVICE_MODE_VALUES)[number]

export const serviceModeLabels: Record<ServiceMode, string> = {
  "autonomous": "AI 托管",
  "operator_assisted": "客服接管"
}

export const SENDER_ROLE_VALUES = [
  'customer',
  'assistant',
  'operator',
  'system',
] as const

export type SenderRole = (typeof SENDER_ROLE_VALUES)[number]

export const senderRoleLabels: Record<SenderRole, string> = {
  "customer": "客户",
  "assistant": "智能助手",
  "operator": "客服",
  "system": "系统"
}

export const VIEW_ROLE_VALUES = [
  'customer',
  'support',
] as const

export type ViewRole = (typeof VIEW_ROLE_VALUES)[number]

export const viewRoleLabels: Record<ViewRole, string> = {
  "customer": "客户",
  "support": "客服工作台"
}

export const ACTOR_TYPE_VALUES = [
  'customer',
  'agent',
  'operator',
  'system',
] as const

export type ActorType = (typeof ACTOR_TYPE_VALUES)[number]

export const actorTypeLabels: Record<ActorType, string> = {
  "customer": "客户",
  "agent": "Agent",
  "operator": "客服",
  "system": "系统"
}

export const PURCHASE_CHANNEL_VALUES = [
  'official_website',
  'official_store',
  'marketplace',
  'authorized_dealer',
  'third_party_seller',
  'offline_retail',
  'unknown',
] as const

export type PurchaseChannel = (typeof PURCHASE_CHANNEL_VALUES)[number]

export const purchaseChannelLabels: Record<PurchaseChannel, string> = {
  "official_website": "品牌官网",
  "official_store": "品牌官方店",
  "marketplace": "电商平台",
  "authorized_dealer": "授权经销商",
  "third_party_seller": "第三方卖家",
  "offline_retail": "线下零售",
  "unknown": "未知"
}

export const LOCALE_VALUES = [
  'CN',
  'US',
  'DE',
  'JP',
  'GB',
  'FR',
  'AU',
  'CA',
] as const

export type Locale = (typeof LOCALE_VALUES)[number]

export const localeLabels: Record<Locale, string> = {
  "CN": "中国大陆",
  "US": "美国",
  "DE": "德国",
  "JP": "日本",
  "GB": "英国",
  "FR": "法国",
  "AU": "澳大利亚",
  "CA": "加拿大"
}
