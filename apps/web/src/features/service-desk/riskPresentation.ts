import type { RiskIncidentView } from '../../api/client'

export function emotionStatus(incident: Pick<RiskIncidentView, 'currentEmotion' | 'emotionTrend'>) {
  const level = { calm: '平稳', dissatisfied: '不满', angry: '激烈', unknown: '未知' }[incident.currentEmotion ?? 'unknown']
  if (incident.emotionTrend === 'rising') return `${level} · 加剧`
  if (incident.emotionTrend === 'falling') return `${level} · 缓和`
  if (incident.emotionTrend === 'stable' && incident.currentEmotion !== 'calm' && incident.currentEmotion !== 'unknown') return `持续${level}`
  return level
}

export function primaryConversation(incident: RiskIncidentView) {
  return incident.primaryConversationId ?? incident.conversationIds[0]
}

export function signalAttention(signal: RiskIncidentView['signals'][number]) {
  if (['resolved', 'ignored'].includes(signal.riskStatus)) return 'closed'
  if (signal.currentAttention) return signal.currentAttention
  return signal.signalActive !== false && !signal.conditions?.analysisStale ? 'active' : 'review'
}

export function followupDeadlines(conditions?: Record<string, unknown>) {
  if (!Array.isArray(conditions?.deadlines)) return []
  return conditions.deadlines.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const value = item as { ticketId?: unknown; dueAt?: unknown }
    return typeof value.ticketId === 'string' && typeof value.dueAt === 'string'
      ? [{ ticketId: value.ticketId, dueAt: value.dueAt }]
      : []
  })
}
