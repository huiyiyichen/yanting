import type { ConsumerProfileView, RiskIncidentDetailView } from '../../api/client'
import { shTimestamp } from '../service-desk/shTime'

export type LaneNode = { key: string; at: number; end?: number; open?: boolean; label: string; title: string; tone?: 'risk' | 'done'; conversationId?: string; levels?: ('calm' | 'dissatisfied' | 'angry')[] }
export type LaneRow = { key: 'contacts' | 'orders' | 'tickets' | 'promises' | 'handling'; label: string; nodes: LaneNode[] }
export type DaySeg = { day: number; gapBefore: boolean }

const DAY = 86400000
const OFFSET = 8 * 3600000
export const dayOf = (ms: number) => Math.floor((ms + OFFSET) / DAY)

/**
 * 多源泳道（全景方案 4.6）：只用本事件关联会话、其订单号、工单号的明确关联；无数据的泳道不出现。
 */
export function buildLanes(detail: RiskIncidentDetailView, profile: ConsumerProfileView | null, now = Date.now()): LaneRow[] {
  const ids = new Set(detail.incident.conversationIds)
  const contexts = detail.contexts.filter((context) => ids.has(context.conversationId))
  const contacts: LaneNode[] = contexts.map((context) => {
    const levels = (detail.emotionHistory ?? []).filter((point) => point.conversationId === context.conversationId).map((point) => point.emotion)
    const at = shTimestamp(context.timeline.find((event) => event.entityType === 'message')?.occurredAt ?? context.firstAt)
    return { key: `c-${context.conversationId}`, at, label: context.conversationId, title: context.conversationId, conversationId: context.conversationId, levels }
  })
  const orderIds = new Set([...detail.incident.orderIds, ...contexts.flatMap((context) => context.orders.map((order) => order.orderId))])
  const orders = new Map<string, LaneNode[]>()
  for (const context of contexts) for (const order of context.orders) {
    if (!orderIds.has(order.orderId) || orders.has(order.orderId)) continue
    orders.set(order.orderId, ([['下单', order.orderedAt], ['付款', order.paidAt], ['发货', order.shippedAt]] as const)
      .filter(([, at]) => at).map(([name, at]) => ({ key: `o-${order.orderId}-${name}`, at: shTimestamp(at), label: name,
        title: `${name} · 订单 ${order.orderId}${order.productName ? ` · ${order.productName}` : ''}` })))
  }
  const ticketNodes: LaneNode[] = []
  const seen = new Set<string>()
  for (const context of contexts) for (const work of context.workOrders) {
    if (seen.has(work.workOrderId)) continue
    seen.add(work.workOrderId)
    const end = work.completedAt ? shTimestamp(work.completedAt) : now
    ticketNodes.push({ key: `w-${work.workOrderId}`, at: shTimestamp(work.createdAt), end, open: !work.completedAt,
      label: `${work.workOrderType} ${work.workOrderId}`, title: `${work.workOrderType} · ${work.workOrderId} · ${work.sourceStatus}`, tone: work.completedAt ? 'done' : undefined })
  }
  for (const ticket of detail.tickets) {
    if (seen.has(ticket.ticketId) || (ticket.sourceRecordId && seen.has(ticket.sourceRecordId))) continue
    seen.add(ticket.ticketId)
    const done = ticket.status === 'resolved'
    ticketNodes.push({ key: `t-${ticket.ticketId}`, at: shTimestamp(ticket.createdAt), end: done ? shTimestamp(ticket.updatedAt) : now, open: !done,
      label: ticket.title, title: `${ticket.title} · ${ticket.ticketId}`, tone: done ? 'done' : undefined })
  }
  const promises: LaneNode[] = (profile && ids.has(profile.conversationId) ? profile.promises : []).map((promise) => ({
    key: `p-${promise.sourceRef}`, at: shTimestamp(promise.madeAt), end: shTimestamp(promise.dueAt),
    label: promise.status === 'due' ? '已到期' : promise.status === 'fulfilled' ? '已兑现' : '待兑现',
    title: promise.fullText || promise.text, tone: promise.status === 'due' ? 'risk' : promise.status === 'fulfilled' ? 'done' : undefined,
  }))
  const handling: LaneNode[] = detail.handlingHistory.map((event) => ({
    key: `h-${event.eventId}`, at: shTimestamp(event.createdAt), label: event.action, title: `${event.actor} · ${event.note}`,
  }))
  return ([
    { key: 'contacts', label: '进线', nodes: contacts },
    { key: 'orders', label: '订单', nodes: [...orders.values()].flat() },
    { key: 'tickets', label: '工单', nodes: ticketNodes },
    { key: 'promises', label: '承诺', nodes: promises },
    { key: 'handling', label: '处置', nodes: handling },
  ] as LaneRow[]).map((lane) => ({ ...lane, nodes: lane.nodes.filter((node) => node.at > 0) })).filter((lane) => lane.nodes.length > 0)
}

/** 横轴按天；相邻有数据的日子间隔超过 3 天时折叠为一个 // 断档。 */
export function daySegments(lanes: LaneRow[]): DaySeg[] {
  const days = [...new Set(lanes.flatMap((lane) => lane.nodes.flatMap((node) => [node.at, node.end ?? node.at]).map(dayOf)))].sort((a, b) => a - b)
  const out: DaySeg[] = []
  days.forEach((day, i) => {
    const prev = days[i - 1]
    if (prev != null && day - prev > 3) out.push({ day, gapBefore: true })
    else {
      if (prev != null) for (let d = prev + 1; d < day; d += 1) out.push({ day: d, gapBefore: false })
      out.push({ day, gapBefore: false })
    }
  })
  return out
}

/** 时间 → 横向百分比；落在折叠区间的时间贴到断档后第一天的开头。 */
export function xPercent(ms: number, segments: DaySeg[]): number {
  if (!segments.length) return 0
  const day = dayOf(ms)
  let index = segments.findIndex((seg) => seg.day >= day)
  if (index < 0) index = segments.length - 1
  const fraction = segments[index].day === day ? ((ms + OFFSET) % DAY) / DAY : 0
  return ((index + fraction) / segments.length) * 100
}
