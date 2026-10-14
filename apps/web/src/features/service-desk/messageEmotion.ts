import type { ConsumerProfileView } from '../../api/client'

type Level = 'calm' | 'dissatisfied' | 'angry'
const idOf = (sourceRef: string) => sourceRef.split(':').at(-1) ?? sourceRef

/** 画像卡情绪轨迹 → 按消息 ID 的规则情绪（只取当前会话的画像）。 */
export function messageEmotions(profile: ConsumerProfileView | null, conversationId: string | null) {
  const result: Record<string, Level> = {}
  if (!profile || profile.conversationId !== conversationId) return result
  for (const point of profile.emotionTrail) {
    if (point.role === 'customer' && point.level) result[idOf(point.sourceRef)] = point.level as Level
  }
  return result
}

/** 情绪升级发生的那条消费者消息。 */
export function escalationMessage(profile: ConsumerProfileView | null, conversationId: string | null) {
  if (!profile?.escalatedAt || profile.conversationId !== conversationId) return null
  const at = Date.parse(profile.escalatedAt)
  const point = profile.emotionTrail.find((p) => p.role === 'customer' && p.level === 'angry' && Date.parse(p.at) === at)
  return point ? idOf(point.sourceRef) : null
}
