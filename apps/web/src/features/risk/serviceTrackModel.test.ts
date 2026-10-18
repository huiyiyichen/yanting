/**
 * 风险页反馈 5 服务轨迹失败方式：
 * T1 主干阶段与订单记录不符（没付款却亮、有售后工单却不亮售后中）；
 * T2 里程碑混入无关会话的工单；承诺没写内容或过期未标已超期；
 * T3 第 N 次进线编号错误，悬停拿不到前次摘要。
 */
import { describe, expect, it } from 'vitest'
import type { ConsumerProfileView, RiskIncidentDetailView } from '../../api/client'
import { buildMilestones, orderStages } from './serviceTrackModel'

const msg = (role: string, body: string, at: string) => ({ entityType: 'message', occurredAt: at, message: { senderRole: role, body } })
const detail = {
  incident: { conversationIds: ['S1', 'S2'], orderIds: ['O1'] },
  contexts: [
    { conversationId: 'S1', firstAt: '2026-05-05T02:00:00Z', orders: [{ orderId: 'O1', paidAt: '2026-05-01T02:00:00Z', shippedAt: '2026-05-02T02:00:00Z', sourceStatus: '已发货' }],
      workOrders: [], timeline: [msg('customer', '还没到', '2026-05-05T02:00:00Z'), msg('operator', '已催快递', '2026-05-05T02:05:00Z')] },
    { conversationId: 'S2', firstAt: '2026-05-08T02:00:00Z', orders: [],
      workOrders: [{ workOrderId: 'W1', workOrderType: '售后退货', createdAt: '2026-05-08T03:00:00Z', completedAt: null, sourceStatus: '处理中' }],
      timeline: [msg('customer', '我要退货', '2026-05-08T02:00:00Z')] },
    { conversationId: 'S9', firstAt: '2026-05-06T02:00:00Z', orders: [], timeline: [],
      workOrders: [{ workOrderId: 'W9', workOrderType: '物流', createdAt: '2026-05-06T02:00:00Z', sourceStatus: '' }] },
  ],
  tickets: [], handlingHistory: [], emotionHistory: [{ conversationId: 'S2', emotion: 'angry' }],
} as unknown as RiskIncidentDetailView
const profile = { conversationId: 'S1', promises: [{ sourceRef: 'm1', text: '明天发', fullText: '明天给您补发', madeAt: '2026-05-05T02:05:00Z',
  dueAt: '2026-05-06T02:05:00Z', status: 'pending', deadline: '' }] } as unknown as ConsumerProfileView

describe('serviceTrack', () => {
  it('T1 订单主干', () => {
    const stages = orderStages(detail)
    expect(stages.map((s) => [s.label, s.done])).toEqual([['付款', true], ['发货', true], ['签收', true], ['售后中', true]])
    const bare = { ...detail, contexts: [{ ...detail.contexts[0], orders: [{ orderId: 'O1', sourceStatus: '待付款' }] }] } as unknown as RiskIncidentDetailView
    expect(orderStages(bare).map((s) => s.done)).toEqual([false, false, false, false])
  })
  it('T2/T3 里程碑', () => {
    const items = buildMilestones(detail, profile, Date.parse('2026-05-09T00:00:00Z'))
    expect(items.map((m) => m.kind)).toEqual(['contact', 'promise', 'contact', 'ticket'])
    expect(items.some((m) => m.kind === 'ticket' && m.id === 'W9')).toBe(false)
    const promise = items[1]; expect(promise.kind === 'promise' && promise.text === '明天给您补发' && promise.status === 'overdue').toBe(true)
    const second = items[2]
    expect(second.kind === 'contact' && second.nth === 2 && second.levels[0] === 'angry').toBe(true)
    expect(second.kind === 'contact' && second.previous).toBe('客户：还没到\n客服：已催快递')
  })
})
