import type { ConsumerServiceAssistantView, MessageView } from '../../api/client'

function sentences(text: string, limit: number) {
  return text.trim().split(/(?<=[。！？!?])\s*|\n+/).filter(Boolean).slice(0, limit)
}

export function handoffBrief(assistant: ConsumerServiceAssistantView | null, messages: MessageView[]) {
  if (assistant && !assistant.stale) {
    return [...new Set([
      ...sentences(assistant.currentQuestion, 1),
      ...sentences(assistant.serviceSummary, 4),
    ])].slice(0, 5)
  }
  const customer = messages.filter((item) => item.senderRole === 'customer' && item.body.trim())
  const service = messages.filter((item) => ['operator', 'assistant'].includes(item.senderRole)
    && item.body.trim() && !/欢迎|请描述您|还有其他|生活愉快/.test(item.body))
  const first = customer[0]
  const latest = customer.at(-1)
  const previousReply = service.at(-1)
  return [
    ...(first && first !== latest ? [`最初咨询：${sentences(first.body, 1).join('')}`] : []),
    ...(latest ? [`客户最新反馈：${sentences(latest.body, 2).join('')}`] : []),
    ...(previousReply ? [`客服曾回复：${sentences(previousReply.body, 2).join('')}`] : []),
  ]
}
