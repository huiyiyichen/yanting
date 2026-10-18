/** 服务轨迹（风险页反馈 5）：顶部订单主干 + 下方按时间排的里程碑卡片；只用本事件关联会话、订单、工单的明确记录。 */
import type { ConsumerProfileView, RiskIncidentDetailView } from '../../api/client'
import { shTimestamp } from '../service-desk/shTime'

type Level = 'calm' | 'dissatisfied' | 'angry'
export type Stage = { key: 'paid' | 'shipped' | 'signed' | 'aftersale'; label: string; at: number | null; done: boolean }
export type Milestone =
  | { kind: 'contact'; key: string; at: number; nth: number; conversationId: string; levels: Level[]; previous: string | null; unanswered: boolean }
  | { kind: 'promise'; key: string; at: number; text: string; dueAt: number; status: 'overdue' | 'pending' | 'fulfilled' }
  | { kind: 'ticket'; key: string; at: number; id: string; type: string; status: string; done: boolean; stalledDays: number }
  | { kind: 'handling'; key: string; at: number; action: string; note: string }

const SIGNED = /签收|已收货|交易成功|已完成/
const STAFF = new Set(['operator', 'assistant', 'staff', 'agent', 'seller'])

/** 订单主干：付款→发货→签收→售后中；有未完结工单或风险事件即视为售后中。签收只认订单状态里的明确字样。 */
/** 工单类型机器值 → 中文（不在卡片上外露 return_refund 等字段）。 */
export const WORK_TYPE: Record<string, string> = { adverse_reaction: '不良反应', return_refund: '售后退货', reship_exchange: '补发换货', offline_payment: '线下打款', logistics: '物流' }

/** 处置事件机器值 → 中文。 */
const HANDLING: Record<string, string> = { in_progress: '开始处理', resolved: '复核关闭', ignored: '忽略风险', reopen: '重新介入', follow_up: '约定跟进', intervene: '开始处理' }

function handlingNote(action: string, note: string): string[] {
  if (action !== 'follow_up') return [note]
  const [iso, ...rest] = note.split('|')
  const at = Date.parse(iso)
  if (Number.isNaN(at)) return [note]
  const d = new Date(at + 8 * 3600000)
  const p = (n: number) => String(n).padStart(2, '0')
  return [`${p(d.getUTCMonth() + 1)}/${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`, rest.join('|')]
}

export function orderStages(detail: RiskIncidentDetailView): Stage[] {
  const ids = new Set(detail.incident.conversationIds)
  const contexts = detail.contexts.filter((c) => ids.has(c.conversationId))
  const orders = contexts.flatMap((c) => c.orders).filter((o) => !detail.incident.orderIds.length || detail.incident.orderIds.includes(o.orderId))
  const order = orders[0] ?? contexts.flatMap((c) => c.orders)[0]
  const works = contexts.flatMap((c) => c.workOrders)
  const firstWork = works.map((w) => shTimestamp(w.createdAt)).filter((t) => t > 0).sort((a, b) => a - b)[0] ?? null
  const paid = order?.paidAt ? shTimestamp(order.paidAt) : null
  const shipped = order?.shippedAt ? shTimestamp(order.shippedAt) : null
  const signed = Boolean(order?.sourceStatus && SIGNED.test(order.sourceStatus))
  const aftersale = works.some((w) => !w.completedAt) || detail.tickets.some((t) => t.status !== 'resolved') || works.length > 0
  return [
    { key: 'paid', label: '付款', at: paid, done: paid != null },
    { key: 'shipped', label: '发货', at: shipped, done: shipped != null },
    { key: 'signed', label: '签收', at: null, done: signed || aftersale && shipped != null },
    { key: 'aftersale', label: '售后中', at: firstWork, done: aftersale },
  ]
}

const clip = (text: string, n = 40) => (text.length > n ? `${text.slice(0, n)}…` : text)

export function buildMilestones(detail: RiskIncidentDetailView, profile: ConsumerProfileView | null, now = Date.now()): Milestone[] {
  const ids = new Set(detail.incident.conversationIds)
  const contexts = detail.contexts.filter((c) => ids.has(c.conversationId))
    .map((c) => ({ c, at: shTimestamp(c.timeline.find((e) => e.entityType === 'message')?.occurredAt ?? c.firstAt) }))
    .filter((x) => x.at > 0).sort((a, b) => a.at - b.at)
  const lastWords = (conversationId: string): string | null => {
    const history = detail.contexts.flatMap((c) => c.historyServices ?? []).find((h) => h.conversationId === conversationId)
    if (history) return [history.latestCustomerMessage && `客户：${clip(history.latestCustomerMessage)}`,
      history.latestStaffMessage && `客服：${clip(history.latestStaffMessage)}`].filter(Boolean).join('\n') || null
    const ctx = detail.contexts.find((c) => c.conversationId === conversationId)
    const msgs = (ctx?.timeline ?? []).map((e) => e.message).filter((m): m is NonNullable<typeof m> => Boolean(m?.body))
    const customer = [...msgs].reverse().find((m) => m.senderRole === 'customer')
    const staff = [...msgs].reverse().find((m) => STAFF.has(m.senderRole))
    return [customer && `客户：${clip(customer.body!)}`, staff && `客服：${clip(staff.body!)}`].filter(Boolean).join('\n') || null
  }
  const out: Milestone[] = contexts.map(({ c, at }, i) => ({
    kind: 'contact', key: `c-${c.conversationId}`, at, nth: i + 1, conversationId: c.conversationId,
    levels: (detail.emotionHistory ?? []).filter((p) => p.conversationId === c.conversationId).map((p) => p.emotion as Level),
    previous: i > 0 ? lastWords(contexts[i - 1].c.conversationId) : null,
    unanswered: [...c.timeline].reverse().find((e) => e.message?.body)?.message?.senderRole === 'customer',
  }))
  const stalled = (at: number, done: boolean) => done || !at ? 0 : Math.max(0, Math.floor((now - at) / 86400000))
  for (const p of profile && ids.has(profile.conversationId) ? profile.promises : []) {
    const dueAt = shTimestamp(p.dueAt)
    const status = p.status === 'fulfilled' ? 'fulfilled' : p.status === 'due' || (dueAt > 0 && dueAt < now) ? 'overdue' : 'pending'
    out.push({ kind: 'promise', key: `p-${p.sourceRef}`, at: shTimestamp(p.madeAt), text: p.fullText || p.text, dueAt, status })
  }
  const seen = new Set<string>()
  for (const { c } of contexts) for (const w of c.workOrders) {
    if (seen.has(w.workOrderId)) continue
    seen.add(w.workOrderId)
    out.push({ kind: 'ticket', key: `w-${w.workOrderId}`, at: shTimestamp(w.createdAt), id: w.workOrderId, type: WORK_TYPE[w.workOrderType] ?? w.workOrderType,
      status: w.sourceStatus, done: Boolean(w.completedAt), stalledDays: stalled(shTimestamp(w.createdAt), Boolean(w.completedAt)) })
  }
  for (const t of detail.tickets) {
    if (seen.has(t.ticketId) || (t.sourceRecordId && seen.has(t.sourceRecordId))) continue
    seen.add(t.ticketId)
    out.push({ kind: 'ticket', key: `t-${t.ticketId}`, at: shTimestamp(t.createdAt), id: t.ticketId, type: t.title,
      status: t.status === 'resolved' ? '已解决' : '处理中', done: t.status === 'resolved',
      stalledDays: stalled(shTimestamp(t.updatedAt ?? t.createdAt), t.status === 'resolved') })
  }
  for (const e of detail.handlingHistory) out.push({ kind: 'handling', key: `h-${e.eventId}`, at: shTimestamp(e.createdAt),
    action: HANDLING[e.action] ?? e.action, note: [e.actor, ...handlingNote(e.action, e.note)].filter(Boolean).join(' · ') })
  return out.filter((m) => m.at > 0).sort((a, b) => a.at - b.at)
}
