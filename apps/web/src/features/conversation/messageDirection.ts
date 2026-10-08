/**
 * 消息方向计算（前端规范第 5.2 节）。
 *
 * 规则：发送方持久化记录，渲染方向由**当前视角**计算，数据本身不翻转。
 *
 * | 发送者            | 客户视角 | 客服视角 |
 * |------------------|---------|---------|
 * | customer         | 右      | 左      |
 * | assistant        | 左      | 右      |
 * | operator         | 左      | 右      |
 * | system           | 居中    | 居中    |
 */

export type SenderRole = 'customer' | 'assistant' | 'operator' | 'system'
export type ViewRole = 'customer' | 'support'
export type MessageSide = 'start' | 'end' | 'center'

/** 服务方：Agent 自动回复与客服人工回复都代表服务方。 */
const SERVICE_SIDE_ROLES: SenderRole[] = ['assistant', 'operator']

export function messageSide(senderRole: SenderRole, viewRole: ViewRole): MessageSide {
  if (senderRole === 'system') {
    return 'center'
  }
  const isService = SERVICE_SIDE_ROLES.includes(senderRole)
  if (viewRole === 'support') {
    // 客服视角：左客户、右服务方
    return isService ? 'end' : 'start'
  }
  // 客户视角：左服务方、右客户
  return isService ? 'start' : 'end'
}

/** 发送者展示名。 */
export function senderLabel(senderRole: SenderRole): string {
  return {
    customer: '客户',
    assistant: '智能助手',
    operator: '客服',
    system: '系统通知',
  }[senderRole]
}

/** 是否应显示为「我方」。 */
export function isOwnMessage(senderRole: SenderRole, viewRole: ViewRole): boolean {
  if (viewRole === 'support') {
    return senderRole === 'operator' || senderRole === 'assistant'
  }
  return senderRole === 'customer'
}

/**
 * 生成幂等键：同一会话同一内容重复提交只落一条消息。
 * 使用随机后缀而不是内容哈希，以便用户确实想重复发送相同文本时也能发送。
 */
export function newClientMessageKey(): string {
  const cryptoObj = globalThis.crypto
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
    return `web-${cryptoObj.randomUUID()}`
  }
  return `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

/** 会话标题：首条客户消息前 16 个字符（前端规范第 5.1 节）。 */
export function conversationTitleFrom(text: string, fallback = '新会话'): string {
  const trimmed = text.trim()
  if (!trimmed) {
    return fallback
  }
  return trimmed.slice(0, 16)
}
