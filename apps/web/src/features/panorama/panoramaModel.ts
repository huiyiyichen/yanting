import type { PanoramaItem } from '../../api/client'

export type Lane = PanoramaItem['lane']
export type PanoramaFilter = 'all' | 'risk' | 'late'
export const LANE_LABEL: Record<Lane, string> = { ai: 'AI 接待中', wait: '待人工', human: '人工处理中' }

const ts = (value?: string | null) => (value ? Date.parse(value) : Number.POSITIVE_INFINITY)

/**
 * 泳道内稳定排序（全景方案 3.4）：待人工按等待起点；AI 接待中高风险在前、其余按进入泳道先后；
 * 人工处理中按接管先后。都不依赖最后活动时间，新消息不会让色块跳位。
 */
export function laneOrder(lane: Lane, items: PanoramaItem[]): PanoramaItem[] {
  const list = items.filter((item) => item.lane === lane)
  const byEnter = (a: PanoramaItem, b: PanoramaItem) => ts(a.laneEnteredAt) - ts(b.laneEnteredAt)
    || a.conversationId.localeCompare(b.conversationId)
  if (lane === 'wait') return list.sort((a, b) => ts(a.waitingSince ?? a.laneEnteredAt) - ts(b.waitingSince ?? b.laneEnteredAt) || byEnter(a, b))
  if (lane === 'ai') return list.sort((a, b) => Number(b.highRisk) - Number(a.highRisk) || byEnter(a, b))
  return list.sort(byEnter)
}

export const waitSeconds = (item: PanoramaItem, now: number) =>
  item.waitingSince ? Math.max(0, Math.floor((now - Date.parse(item.waitingSince)) / 1000)) : null

export const isLate = (item: PanoramaItem, now: number) => (waitSeconds(item, now) ?? 0) >= 120

export function matches(item: PanoramaItem, filter: PanoramaFilter, now: number): boolean {
  if (filter === 'risk') return item.highRisk
  if (filter === 'late') return isLate(item, now)
  return true
}

/** m:ss，满一小时 h:mm:ss。 */
export function clock(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = String(seconds % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}
