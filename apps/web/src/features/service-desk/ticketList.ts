import type { TicketView } from '../../api/client'
import { ticketDeadline } from './ticketDeadline'

export type StatusGroup = 'pending' | 'in_progress' | 'waiting' | 'resolved'
export type QuickFilter = 'mine' | 'unassigned' | 'due'
export const statusGroups: Array<{ key: StatusGroup; label: string }> = [
  { key: 'pending', label: '待受理' }, { key: 'in_progress', label: '处理中' },
  { key: 'waiting', label: '等待反馈' }, { key: 'resolved', label: '已完成' },
]
export const groupOf = (status: TicketView['status']): StatusGroup =>
  status === 'waiting_customer' || status === 'waiting_internal' ? 'waiting' : status

const groupRank: Record<StatusGroup, number> = { pending: 0, in_progress: 1, waiting: 2, resolved: 3 }
const urgency = { overdue: 0, soon: 1, scheduled: 2, none: 3 } as const
const weight: Record<TicketView['priority'], number> = { urgent: 0, high: 1, normal: 2, low: 3 }
const time = (value?: string | null, fallback = Infinity) => {
  const t = value ? new Date(value).getTime() : NaN
  return Number.isFinite(t) ? t : fallback
}

/** 组内顺序：未完成按 已到期→即将到期→优先级→期限早→最近更新；已完成按最近更新。 */
export function compareTickets(a: TicketView, b: TicketView, now: number) {
  const ga = groupRank[groupOf(a.status)], gb = groupRank[groupOf(b.status)]
  if (ga !== gb) return ga - gb
  if (a.status === 'resolved') return time(b.updatedAt, 0) - time(a.updatedAt, 0)
  return urgency[ticketDeadline(a, now)] - urgency[ticketDeadline(b, now)]
    || weight[a.priority] - weight[b.priority]
    || time(a.dueAt) - time(b.dueAt)
    || time(b.updatedAt, 0) - time(a.updatedAt, 0)
}

/** 快捷筛选可叠加（与）；“我的/待分配/到期”只看未完成。 */
export function matchesQuick(row: TicketView, quick: QuickFilter[], operator: string, now: number) {
  if (!quick.length) return true
  if (row.status === 'resolved') return false
  return quick.every((q) => q === 'mine' ? row.assignee === operator
    : q === 'unassigned' ? !row.assignee
      : ['overdue', 'soon'].includes(ticketDeadline(row, now)))
}

/** 期限一眼可读：超期多久 / 还剩多久；更远只给日期由调用方显示。 */
export function dueText(row: Pick<TicketView, 'dueAt' | 'status'>, now: number): string {
  const state = ticketDeadline(row, now)
  if (state !== 'overdue' && state !== 'soon') return ''
  const diff = Math.abs(time(row.dueAt) - now)
  const minutes = Math.max(1, Math.round(diff / 60000))
  const span = minutes < 60 ? `${minutes} 分钟` : minutes < 48 * 60 ? `${Math.round(minutes / 60)} 小时` : `${Math.round(minutes / 1440)} 天`
  return state === 'overdue' ? `超期 ${span}` : `还剩 ${span}`
}
