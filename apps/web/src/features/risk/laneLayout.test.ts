/**
 * 多源泳道（全景方案 4.6 / 4.12）失败方式：
 * F7 泳道出现与本事件无明确关联的会话或工单。
 * L1 无数据的泳道仍显示。
 * L2 超过 3 天的空白没有折叠，横轴被拉长。
 */
import { describe, expect, it } from 'vitest'
import type { RiskIncidentDetailView } from '../../api/client'
import { buildLanes, dayOf, daySegments, xPercent } from './laneLayout'

const ctx = (id: string, at: string, workOrders: object[] = []) => ({ conversationId: id, firstAt: at, orders: [], workOrders,
  timeline: [{ entityType: 'message', occurredAt: at }] })
const detail = {
  incident: { conversationIds: ['S1'], orderIds: [] },
  contexts: [ctx('S1', '2026-05-05T10:00:00+08:00', [{ workOrderId: 'W1', workOrderType: '售后退货', createdAt: '2026-05-10T10:00:00+08:00', completedAt: null, sourceStatus: '处理中' }]),
    ctx('S9', '2026-05-06T10:00:00+08:00', [{ workOrderId: 'W9', workOrderType: '物流', createdAt: '2026-05-06T10:00:00+08:00', sourceStatus: '' }])],
  tickets: [], handlingHistory: [], emotionHistory: [],
} as unknown as RiskIncidentDetailView

describe('laneLayout', () => {
  it('F7/L1 只取关联会话的数据，空泳道不出现', () => {
    const lanes = buildLanes(detail, null, Date.parse('2026-05-11T00:00:00+08:00'))
    expect(lanes.map((lane) => lane.key)).toEqual(['contacts', 'tickets'])
    expect(lanes[0].nodes.map((node) => node.conversationId)).toEqual(['S1'])
    expect(lanes[1].nodes.map((node) => node.key)).toEqual(['w-W1'])
    expect(lanes[1].nodes[0].open).toBe(true)
  })
  it('L2 超 3 天空白折叠为断档', () => {
    const lanes = [{ key: 'contacts' as const, label: '', nodes: [
      { key: 'a', at: Date.parse('2026-05-01T10:00:00+08:00'), label: '', title: '' },
      { key: 'b', at: Date.parse('2026-05-02T10:00:00+08:00'), label: '', title: '' },
      { key: 'c', at: Date.parse('2026-05-20T10:00:00+08:00'), label: '', title: '' }] }]
    const segs = daySegments(lanes)
    expect(segs).toHaveLength(3)
    expect(segs[2].gapBefore).toBe(true)
    expect(xPercent(Date.parse('2026-05-01T00:00:00+08:00'), segs)).toBeCloseTo(0)
    expect(segs[0].day).toBe(dayOf(Date.parse('2026-05-01T10:00:00+08:00')))
  })
})
