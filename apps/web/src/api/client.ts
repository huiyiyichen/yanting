/**
 * 后端 API 客户端。
 *
 * 定位（工程规范第 13.1 节）：浏览器只保存界面偏好与按会话/角色隔离的未发送草稿；
 * 已发送消息、案件、申请与评价一律以后端为准。
 *
 * 权限：客户接口与客服接口在**服务端**分别校验角色；这里的
 * `X-Demo-View-Role` 只是本机演示用的角色声明，不是生产认证。
 */
import type { components } from '../contracts/api'
import { getDemoOperator } from '../features/service-desk/operator'

export type ConversationSummary = components['schemas']['ConversationSummary']
export type MessageView = components['schemas']['MessageView']
export type SendMessageResponse = components['schemas']['SendMessageResponse']
export type QueueItem = components['schemas']['QueueItem']
export type CaseView = components['schemas']['CaseView']
export type RequestView = components['schemas']['RequestView']
export type EvidenceView = components['schemas']['EvidenceView']
export type RatingView = components['schemas']['RatingView']
export type CloseConversationView = components['schemas']['CloseConversationView']
export type ServiceModeView = components['schemas']['ServiceModeView']
export type SuggestionSetView = components['schemas']['SuggestionSetView']
export type SuggestionView = components['schemas']['SuggestionView']
export type AttachmentView = components['schemas']['AttachmentView']
export type VisionAvailabilityView = components['schemas']['VisionAvailabilityView']
export type HealthResponse = components['schemas']['HealthResponse']
export type CapabilityStatus = components['schemas']['CapabilityStatus']
export type ModelConfigView = components['schemas']['ModelConfigView']
export type ModelProviderView = components['schemas']['ModelProviderView']
export type TestModelView = components['schemas']['TestModelView']
export type TestRerankView = components['schemas']['TestRerankView']
export type OnboardingView = components['schemas']['OnboardingView']
export type KnowledgeOverviewView = components['schemas']['KnowledgeOverviewWithBasesView']
export type KnowledgeBaseItem = components['schemas']['KnowledgeBaseItem']
export type KnowledgeDocumentItem = components['schemas']['KnowledgeDocumentItem']
export type WorkOrderView = components['schemas']['WorkOrderView']
export type WorkOrderItem = components['schemas']['WorkOrderItem']
export type PromptListView = components['schemas']['PromptListView']
export type PromptItem = components['schemas']['PromptItem']
export type PromptTemplateView = components['schemas']['PromptTemplateView']
export type SaveModelConfigView = components['schemas']['SaveModelConfigView']
export type SwitchModelView = components['schemas']['SwitchModelView']
export type ConsumerServiceContextView = components['schemas']['ConsumerServiceContextView']
export type ConsumerServiceAssistantView = components['schemas']['ConsumerServiceAssistantView']
export type ReplyEmpathyDimension = components['schemas']['ReplyEmpathyDimension']
export type RiskEmotionView = components['schemas']['RiskEmotionView']
export type RiskEmotionComparisonView = components['schemas']['RiskEmotionComparisonView']
export type RiskServicePointView = components['schemas']['RiskServicePointView']
export type RiskAlertView = components['schemas']['RiskAlertView']
export type RiskAlertDetailView = components['schemas']['RiskAlertDetailView']
export type ServiceRiskType = components['schemas']['ServiceRiskType']
export type ServiceRiskLevel = components['schemas']['ServiceRiskLevel']
export type ServiceRiskStatus = components['schemas']['ServiceRiskStatus']
export type ReceptionItem = components['schemas']['ReceptionItemView']
export type ReceptionSnapshot = components['schemas']['ReceptionSnapshotView']
export type ServiceWorkOrder = components['schemas']['ServiceWorkOrderView']
export type TicketView = components['schemas']['TicketView']
export type TicketCreateRequest = components['schemas']['TicketCreateRequest']
export type TicketUpdateRequest = components['schemas']['TicketUpdateRequest']
export type TicketDetail = NonNullable<TicketCreateRequest['localDetail']>
export type DemoOperatorRosterView = components['schemas']['DemoOperatorRosterView']
export type RiskIncidentView = components['schemas']['RiskIncidentView']
export type RiskIncidentDetailView = components['schemas']['RiskIncidentDetailView']
export type RiskJudgmentView = components['schemas']['RiskJudgmentView']
export type RiskJudgmentRequest = components['schemas']['RiskJudgmentRequest']
export type RiskJudgmentExportView = components['schemas']['RiskJudgmentExportView']
export type KnowledgeEditorView = components['schemas']['KnowledgeEditorView']
export type KnowledgeEditRequest = components['schemas']['KnowledgeEditRequest']
export type KnowledgeProductView = components['schemas']['KnowledgeProductView']
export type KnowledgeSearchView = components['schemas']['KnowledgeSearchView']
export type PromptRevisionView = components['schemas']['PromptRevisionView']
export type ReceptionStatsView = components['schemas']['ReceptionStatsView']
export type ServiceMemoryView = components['schemas']['ServiceMemoryView']
export type ServiceBreakpointAssessmentView = components['schemas']['ServiceBreakpointAssessmentView']

export type ViewRoleHeader = 'customer' | 'support'

/**
 * 规范化后的案件视图：把生成类型中标为可选的数组字段收敛为必填数组。
 *
 * 后端始终返回这些字段（Pydantic 默认值），但 OpenAPI 会把带默认值的字段
 * 标成可选。与其在每个组件里写 `?? []`，不如在客户端边界统一收敛一次。
 */
export type NormalizedCaseView = CaseView & {
  customerIntents: NonNullable<CaseView['customerIntents']>
  missingFacts: NonNullable<CaseView['missingFacts']>
  allowedActions: NonNullable<CaseView['allowedActions']>
  forbiddenActions: NonNullable<CaseView['forbiddenActions']>
  evidence: NonNullable<CaseView['evidence']>
  requests: NonNullable<CaseView['requests']>
}

/** 候选集合：`items` 在生成类型中可选，边界处收敛为必填数组。 */
export type NormalizedSuggestionSet = SuggestionSetView & {
  items: NonNullable<SuggestionSetView['items']>
}

function normalizeSuggestionSet(value: SuggestionSetView): NormalizedSuggestionSet {
  const record = value as unknown as Record<string, unknown>
  if (!Array.isArray(record.items)) {
    record.items = []
  }
  return value as NormalizedSuggestionSet
}

const ARRAY_KEYS = [
  'forbiddenActions',
  'allowedActions',
  'customerIntents',
  'missingFacts',
  'evidence',
  'requests',
] as const

function normalizeCaseView(value: CaseView): NormalizedCaseView {
  const record = value as unknown as Record<string, unknown>
  for (const key of ARRAY_KEYS) {
    if (!Array.isArray(record[key])) {
      record[key] = []
    }
  }
  return value as NormalizedCaseView
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: string | null

  constructor(status: number, code: string, message: string, detail: string | null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }

  /** 角色不允许类错误必须显式提示，不能静默重试或回退。 */
  get isPermissionDenied(): boolean {
    return this.status === 403
  }

  /** 冲突类错误（重复批准、旧版本确认、托管期间发送）需要用户刷新后再操作。 */
  get isConflict(): boolean {
    return this.status === 409
  }
}

const baseUrl = import.meta.env.VITE_API_BASE ?? ''

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; role?: ViewRoleHeader } = {},
): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (options.role) {
    headers['X-Demo-View-Role'] = options.role
    if (options.role === 'support') headers['X-Demo-Operator'] = getDemoOperator()
  }

  let response: Response
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch (error) {
    throw new ApiError(
      0,
      'network_error',
      `无法连接后端服务：${(error as Error).message}`,
      '请确认后端已启动（默认 http://127.0.0.1:8000）',
    )
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text) as unknown
    } catch {
      // Reverse proxies and crashed dev servers may return HTML/plain text.
      // Keep the UI error actionable instead of leaking a JSON parse exception.
      payload = null
    }
  }

  if (!response.ok) {
    const envelope = payload as
      | { error?: { code?: string; message?: string; detail?: string }; detail?: unknown }
      | null
    const fallback = typeof envelope?.detail === 'string' ? envelope.detail : null
    throw new ApiError(
      response.status,
      envelope?.error?.code ?? 'http_error',
      envelope?.error?.message ?? fallback
      ?? (response.status >= 500 ? '后端服务暂不可用，请检查后端服务' : `请求失败：HTTP ${response.status}`),
      envelope?.error?.detail ?? null,
    )
  }

  return payload as T
}

async function uploadImage(path: string, file: File, role: ViewRoleHeader): Promise<AttachmentView> {
  const form = new FormData()
  form.append('file', file)
  const headers: Record<string, string> = { 'X-Demo-View-Role': role }
  if (role === 'support') headers['X-Demo-Operator'] = getDemoOperator()
  const response = await fetch(`${baseUrl}${path}`, { method: 'POST', headers, body: form })
  const text = await response.text()
  let payload: unknown = null
  try { payload = text ? JSON.parse(text) : null } catch { /* HTTP errors can be plain text. */ }
  if (!response.ok) {
    const envelope = payload as { error?: { message?: string; detail?: string } } | null
    throw new ApiError(
      response.status, 'upload_failed',
      envelope?.error?.message ?? `图片上传失败：HTTP ${response.status}`,
      envelope?.error?.detail ?? null,
    )
  }
  return payload as AttachmentView
}

/** 客户侧接口。响应**不含**任何内部判断字段（AC-24）。 */
export const customerApi = {
  handoff: (conversationId: string) =>
    request<ServiceModeView>(`/api/customer/conversations/${conversationId}/handoff`, {
      method: 'POST', role: 'customer',
    }),
  deleteConversation: (conversationId: string) =>
    deleteConversation(`/api/customer/conversations/${conversationId}`, 'customer'),

  listConversations: (customerId = 'CUST-DEMO-01') =>
    request<ConversationSummary[]>(
      `/api/customer/conversations?customer_id=${encodeURIComponent(customerId)}`,
      { role: 'customer' },
    ),

  createConversation: (customerId = 'CUST-DEMO-01') =>
    request<ConversationSummary>('/api/customer/conversations', {
      method: 'POST',
      body: { customerId },
      role: 'customer',
    }),

  listMessages: (conversationId: string) =>
    request<MessageView[]>(`/api/customer/conversations/${conversationId}/messages`, {
      role: 'customer',
    }),

  sendMessage: (
    conversationId: string,
    body: string,
    clientMessageKey: string,
    attachmentIds: string[] = [],
  ) =>
    request<SendMessageResponse>(`/api/customer/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: { body, clientMessageKey, attachmentIds },
      role: 'customer',
    }),

  getRating: (conversationId: string) =>
    request<RatingView | null>(`/api/customer/conversations/${conversationId}/rating`, {
      role: 'customer',
    }),

  /**
   * 新会话开场白与快捷选项（唯一来源在后端）。
   *
   * 前端只在「该会话还没有客户消息」时展示快捷选项；点了就是发一条普通客户消息，
   * 走同一个发送接口，不做特殊分支。
   */
  onboarding: () => request<OnboardingView>('/api/customer/onboarding', { role: 'customer' }),
  submitRating: (
    conversationId: string,
    action: 'request' | 'submit' | 'skip',
    rating?: number,
  ) =>
    request<RatingView>(`/api/customer/conversations/${conversationId}/rating`, {
      method: 'POST',
      body: { action, rating },
      role: 'customer',
    }),

  /** 图片能力真实状态：未配置多模态时前端据此提示，而不是假装能看图。 */
  vision: () => request<VisionAvailabilityView>('/api/customer/vision', { role: 'customer' }),

  uploadAttachment: (conversationId: string, file: File) =>
    uploadImage(`/api/customer/conversations/${conversationId}/attachments`, file, 'customer'),
}

/** 客服侧接口。仅客服工作台挂载。 */
export const supportApi = {
  deleteConversation: (conversationId: string) =>
    deleteConversation(`/api/support/conversations/${conversationId}`, 'support'),

  queue: () => request<QueueItem[]>('/api/support/queue', { role: 'support' }),

  serviceQueue: () =>
    request<QueueItem[]>('/api/support/service-queue', { role: 'support' }),

  serviceContext: (conversationId: string) =>
    request<ConsumerServiceContextView>(
      `/api/support/conversations/${conversationId}/service-context`,
      { role: 'support' },
    ),

  assistant: (conversationId: string) =>
    request<ConsumerServiceAssistantView | null>(
      `/api/support/conversations/${conversationId}/assistant`,
      { role: 'support' },
    ),
  memory: (conversationId: string) =>
    request<ServiceMemoryView>(`/api/support/reception/${conversationId}/memory`, { role: 'support' }),
  reception: () => request<ReceptionSnapshot>('/api/support/reception/queue', { role: 'support' }),
  receptionMessages: (id: string) =>
    request<MessageView[]>(`/api/support/reception/${id}/messages`, { role: 'support' }),
  uploadAttachment: (id: string, file: File) =>
    uploadImage(`/api/support/reception/${id}/attachments`, file, 'support'),
  sendReceptionMessage: (id: string, body: string, clientMessageKey: string, attachmentIds: string[] = []) =>
    request<MessageView>(`/api/support/reception/${id}/messages`, {
      method: 'POST', body: { body, clientMessageKey, attachmentIds }, role: 'support',
    }),
  markSeen: (id: string, revision: number) =>
    request(`/api/support/reception/${id}/seen`, {
      method: 'POST', body: { revision }, role: 'support',
    }),
  setReceptionMode: (id: string, mode: 'autonomous' | 'operator_assisted') =>
    request<ServiceModeView>(`/api/support/reception/${id}/service-mode`, {
      method: 'POST', body: { mode }, role: 'support',
    }),
  generateAssistant: (id: string) =>
    request<ConsumerServiceAssistantView>(`/api/support/reception/${id}/assistant`, {
      method: 'POST', role: 'support',
    }),
  assistantAction: (id: string, inputHash: string, style: string, action: 'adopt' | 'ignore') =>
    request(`/api/support/reception/${id}/suggestion-action`, {
      method: 'POST', body: { inputHash, style, action }, role: 'support',
    }),
  sourceWorkOrders: () =>
    request<ServiceWorkOrder[]>('/api/support/reception/work-orders/all', { role: 'support' }),

  riskAlerts: (filters: {
    riskType?: ServiceRiskType
    riskLevel?: ServiceRiskLevel
    riskStatus?: ServiceRiskStatus
  } = {}) => {
    const query = new URLSearchParams()
    if (filters.riskType) query.set('risk_type', filters.riskType)
    if (filters.riskLevel) query.set('risk_level', filters.riskLevel)
    if (filters.riskStatus) query.set('risk_status', filters.riskStatus)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request<RiskAlertView[]>(`/api/support/risk-alerts${suffix}`, { role: 'support' })
  },

  riskAlertDetail: (alertId: string) =>
    request<RiskAlertDetailView>(`/api/support/risk-alerts/${alertId}`, { role: 'support' }),

  updateRiskAlertStatus: (
    alertId: string,
    status: ServiceRiskStatus,
    note = '',
  ) =>
    request<RiskAlertView>(`/api/support/risk-alerts/${alertId}/status`, {
      method: 'POST',
      body: { status, note },
      role: 'support',
    }),

  listMessages: (conversationId: string) =>
    request<MessageView[]>(`/api/support/conversations/${conversationId}/messages`, {
      role: 'support',
    }),

  caseDetail: async (conversationId: string) => {
    const result = await request<CaseView | null>(
      `/api/support/conversations/${conversationId}/case`,
      { role: 'support' },
    )
    return result ? normalizeCaseView(result) : null
  },

  sendMessage: (conversationId: string, body: string, clientMessageKey: string) =>
    request<MessageView>(`/api/support/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: { body, clientMessageKey },
      role: 'support',
    }),

  setServiceMode: (conversationId: string, mode: 'autonomous' | 'operator_assisted') =>
    request<ServiceModeView>(`/api/support/conversations/${conversationId}/service-mode`, {
      method: 'POST',
      body: { mode },
      role: 'support',
    }),

  /**
   * 结束服务：关闭案件并同时开放客户评价入口。
   *
   * 合成一个动作是有意的：分两步会出现「已结束但评价入口没开」的中间态。
   */
  closeConversation: (conversationId: string, reason = '') =>
    request<CloseConversationView>(`/api/support/conversations/${conversationId}/close`, {
      method: 'POST',
      body: { reason },
      role: 'support',
    }),

  pendingRequests: () =>
    request<RequestView[]>('/api/support/requests/pending', { role: 'support' }),

  reviewRequest: (
    requestId: string,
    payload: {
      action: 'approve' | 'reject' | 'request_information'
      reason?: string
      reasonText?: string
      expectedRevision?: number
      expectedPayloadHash?: string
    },
  ) =>
    request<RequestView>(`/api/support/requests/${requestId}/review`, {
      method: 'POST',
      body: payload,
      role: 'support',
    }),

  auditTrail: (conversationId: string) =>
    request<Record<string, unknown>[]>(`/api/support/audit/${conversationId}`, {
      role: 'support',
    }),

  /** 读取当前话术候选。新客户消息到达后 expires=true，不得静默发送。 */
  suggestions: async (conversationId: string) => {
    const result = await request<SuggestionSetView | null>(
      `/api/support/conversations/${conversationId}/suggestions`,
      { role: 'support' },
    )
    return result ? normalizeSuggestionSet(result) : null
  },

  /** 生成三种措辞。必须来自真实模型，失败时向上暴露错误。 */
  generateSuggestions: async (conversationId: string) =>
    normalizeSuggestionSet(
      await request<SuggestionSetView>(
        `/api/support/conversations/${conversationId}/suggestions/generate`,
        { method: 'POST', role: 'support' },
      ),
    ),

  /** 采用或忽略候选：采用只写草稿，不发送。 */
  suggestionAction: (
    conversationId: string,
    variant: string,
    action: 'adopt' | 'ignore',
  ) =>
    request<SuggestionView>(
      `/api/support/conversations/${conversationId}/suggestions/action`,
      { method: 'POST', body: { variant, action }, role: 'support' },
    ),
}

/**
 * 删除会话（两侧同一语义）：级联删业务数据，**审计保留**。
 * 本机 Demo 会累积大量演示会话，没有删除入口就只能手工清库。
 */
async function deleteConversation(path: string, role: ViewRoleHeader): Promise<void> {
  await request<{ conversationId: string; deleted: Record<string, number> }>(path, {
    method: 'DELETE',
    role,
  })
}

export const healthApi = {
  health: () => request<HealthResponse>('/api/health'),
  probe: () => request<Record<string, unknown>>('/api/health/probe', { method: 'POST' }),
}

/**
 * 平台配置接口（模型配置等）。
 *
 * 这是**本机 Demo 的运维视角**：只有 `support` 角色可读，服务端保证不返回密钥。
 * 页面据此展示真实模型名、网关主机与健康状态，并提供真实的连通性测试。
 */
export const platformApi = {
  models: () => request<ModelConfigView>('/api/platform/models', { role: 'support' }),
  knowledge: () => request<KnowledgeOverviewView>('/api/platform/knowledge', { role: 'support' }),
  knowledgeBases: () =>
    request<KnowledgeBaseItem[]>('/api/platform/knowledge-bases', { role: 'support' }),
  /** 保存模型配置（地址/密钥/模型）；密钥只进不出，返回的是掩码 */
  saveConfig: (payload: {
    baseUrl?: string
    apiKey?: string
    model?: string
    visionModel?: string
    /** 向量：本地 ONNX 或远端 OpenAI 兼容服务 */
    embeddingBackend?: string
    embeddingModel?: string
    embeddingPath?: string
    embeddingBaseUrl?: string
    embeddingApiKey?: string
    embeddingDimension?: number
    /** 重排序（可选精排）：纯 HTTP，保存后立即生效 */
    rerankBackend?: string
    rerankBaseUrl?: string
    rerankApiKey?: string
    rerankModel?: string
  }) =>
    request<SaveModelConfigView>('/api/platform/models/config', {
      method: 'PUT',
      body: payload,
      role: 'support',
    }),
  workOrders: () => request<WorkOrderView>('/api/platform/work-orders', { role: 'support' }),
  prompts: () => request<PromptListView>('/api/platform/prompts', { role: 'support' }),
  /** 切换生效的文本模型（服务端会校验模型确实存在，并持久化） */
  switchModel: (model: string) =>
    request<SwitchModelView>('/api/platform/models/active', {
      method: 'POST',
      body: { model },
      role: 'support',
    }),
  /** 提示词模板（可写）：列表 / 新增 / 编辑 / 启停 */
  templates: () =>
    request<PromptTemplateView[]>('/api/platform/prompt-templates', { role: 'support' }),
  createTemplate: (payload: { code: string; name: string; scenario: string; content: string }) =>
    request<PromptTemplateView>('/api/platform/prompt-templates', {
      method: 'POST',
      body: payload,
      role: 'support',
    }),
  updateTemplate: (
    templateId: string,
    payload: { name?: string; scenario?: string; content?: string; expectedRevision?: number },
  ) =>
    request<PromptTemplateView>(`/api/platform/prompt-templates/${templateId}`, {
      method: 'PUT',
      body: payload,
      role: 'support',
    }),
  setTemplateStatus: (templateId: string, status: 'enabled' | 'disabled') =>
    request<PromptTemplateView>(`/api/platform/prompt-templates/${templateId}/status`, {
      method: 'POST',
      body: { status },
      role: 'support',
    }),
  testModel: (model: string) =>
    request<TestModelView>('/api/platform/models/test', {
      method: 'POST',
      body: { model },
      role: 'support',
    }),
  /** 重排序连通性测试：真发一次排序请求，回显两句话的先后顺序 */
  testRerank: () =>
    request<TestRerankView>('/api/platform/rerank/test', {
      method: 'POST',
      body: {},
      role: 'support',
    }),
}

export const deskApi = {
  operators: () => request<DemoOperatorRosterView>('/api/support/desk/operators', { role: 'support' }),
  stats: () => request<ReceptionStatsView>('/api/support/desk/stats', { role: 'support' }),
  tickets: (conversationId?: string) => request<TicketView[]>(
    `/api/support/desk/tickets${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ''}`, { role: 'support' }),
  ticket: (id: string) => request<TicketView>(`/api/support/desk/tickets/${id}`, { role: 'support' }),
  createTicket: (body: TicketCreateRequest) => request<TicketView>('/api/support/desk/tickets', { method: 'POST', body, role: 'support' }),
  updateTicket: (id: string, body: TicketUpdateRequest) => request<TicketView>(`/api/support/desk/tickets/${id}`, { method: 'PUT', body, role: 'support' }),
  risks: () => request<RiskIncidentView[]>('/api/support/desk/risks', { role: 'support' }),
  conversationRisks: (id: string) => request<RiskIncidentView[]>(
    `/api/support/desk/conversations/${encodeURIComponent(id)}/risks`, { role: 'support' }),
  risk: (id: string) => request<RiskIncidentDetailView>(`/api/support/desk/risks/${id}`, { role: 'support' }),
  interveneRisk: (id: string, conversationId: string, expectedVersion: string) =>
    request<RiskIncidentDetailView>(`/api/support/desk/risks/${id}/intervene`, {
      method: 'POST', body: { conversationId, expectedVersion }, role: 'support',
    }),
  judgeRisk: (id: string, alertId: string, body: RiskJudgmentRequest) =>
    request<RiskIncidentDetailView>(`/api/support/desk/risks/${id}/signals/${alertId}/judgment`, { method: 'POST', body, role: 'support' }),
  exportRiskJudgments: () => request<RiskJudgmentExportView>('/api/support/desk/risk-judgments/export', { role: 'support' }),
  breakpoints: (id: string) => request<ServiceBreakpointAssessmentView>(`/api/support/desk/breakpoints/${id}`, { role: 'support' }),
  analyzeBreakpoints: (id: string) => request<ServiceBreakpointAssessmentView>(`/api/support/desk/breakpoints/${id}`, { method: 'POST', role: 'support' }),
  scan: () => request<components['schemas']['RiskScanView']>('/api/support/desk/risks/scan', { method: 'POST', role: 'support' }),
  updateRisk: (id: string, status: 'in_progress' | 'resolved' | 'ignored' | 'reopen', note: string, expectedVersion: string) =>
    request<RiskIncidentDetailView>(`/api/support/desk/risks/${id}/status`, { method: 'POST', body: { status, note, expectedVersion }, role: 'support' }),
}

export const knowledgeApi = {
  products: () => request<KnowledgeProductView[]>('/api/platform/knowledge/products', { role: 'support' }),
  documents: () => request<KnowledgeEditorView[]>('/api/platform/knowledge/documents', { role: 'support' }),
  document: (id: string) => request<KnowledgeEditorView>(`/api/platform/knowledge/documents/${id}`, { role: 'support' }),
  create: (body: KnowledgeEditRequest) => request<KnowledgeEditorView>('/api/platform/knowledge/documents', { method: 'POST', body, role: 'support' }),
  save: (id: string, body: KnowledgeEditRequest) => request<KnowledgeEditorView>(`/api/platform/knowledge/documents/${id}`, { method: 'PUT', body, role: 'support' }),
  toggle: (id: string, enabled: boolean) => request<KnowledgeEditorView>(`/api/platform/knowledge/documents/${id}/status`, { method: 'POST', body: { enabled }, role: 'support' }),
  createBase: (name: string) => request<{ knowledgeBaseId: string; name: string }>('/api/platform/knowledge/bases', { method: 'POST', body: { name }, role: 'support' }),
  publish: () => request<components['schemas']['KnowledgePublishView']>('/api/platform/knowledge/publish', { method: 'POST', role: 'support' }),
  search: (query: string, knowledgeBaseId?: string, productSku?: string) => request<KnowledgeSearchView>('/api/platform/knowledge/search', { method: 'POST', body: { query, knowledgeBaseId, productSku }, role: 'support' }),
}

export const promptApi = {
  bind: (id: string, purpose: string) => request<PromptTemplateView>(`/api/platform/prompt-templates/${id}/binding`, { method: 'POST', body: { purpose }, role: 'support' }),
  revisions: (id: string) => request<PromptRevisionView[]>(`/api/platform/prompt-templates/${id}/revisions`, { role: 'support' }),
  restore: (id: string, revision: number, expectedRevision: number) => request<PromptTemplateView>(`/api/platform/prompt-templates/${id}/restore`, { method: 'POST', body: { revision, expectedRevision }, role: 'support' }),
}
