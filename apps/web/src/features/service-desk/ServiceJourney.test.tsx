/**
 * 轨迹页（插件 C）。先列失败方式：
 * J1 轨迹里重复出现聊天原文（左侧已可见），而不是业务节点。
 * J2 承诺只出现“作出”节点，没有到期节点和状态；已过期仍显示待兑现。
 * J3 节点不按时间排序；同一天每行都重复日期。
 * J4 别的会话的画像被拼进当前会话轨迹。
 * J5 “本次进线”用了被订单带早的 firstAt，而不是本次第一条消息。
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ConsumerProfileView, ConsumerServiceContextView } from '../../api/client'
import { ServiceJourney, journeyNodes } from './ServiceJourney'

const context = {
  conversationId: 'S1', firstAt: '2026-05-07T17:32:00', buyerAlias: '魏h**', buyerAliases: [], orders: [], workOrders: [],
  timeline: [{ eventId: 'e1', occurredAt: '2026-05-07T17:32:00', message: { body: '箱子是空的', senderRole: 'customer' } }],
  serviceNodes: [
    { occurredAt: '2026-05-07T18:00:00', kind: '工单创建', title: 'KOC7263722', status: '处理中', sourceRecordId: 'w1' },
    { occurredAt: '2026-05-01T10:00:00', kind: '下单', title: '6920621990731110707', status: '已发货', sourceRecordId: 'o1' },
    { occurredAt: '2026-05-01T10:05:00', kind: '付款', title: '6920621990731110707', sourceRecordId: 'o1' },
  ],
  historyServices: [], historyConversationIds: [], products: [], datasetId: 'd', batchId: 'b',
} as unknown as ConsumerServiceContextView
const profile = {
  conversationId: 'S1', escalatedAt: '2026-05-07T17:38:00', emotionTrail: [],
  promises: [{ text: '3 个工作日未到账则线下补款', madeAt: '2026-05-05T10:00:00', dueAt: '2026-05-08T23:59:00', status: 'pending', sourceRef: 'message:S0:m1' }],
} as unknown as ConsumerProfileView

describe('ServiceJourney', () => {
  it('J1 shows business nodes, not chat text', () => {
    render(<ServiceJourney context={context} profile={profile} />)
    expect(screen.queryByText('箱子是空的')).toBeNull()
    expect(screen.getByText('工单创建')).toBeInTheDocument()
    expect(screen.getAllByText('…0707').length).toBeGreaterThan(0)
  })
  it('J2 promise has a due node; overdue reads 已到期', () => {
    const nodes = journeyNodes(context, profile, Date.parse('2026-05-10T00:00:00'))
    const due = nodes.find((n) => n.kind === '承诺到期')!
    expect(due.state).toBe('已到期')
    expect(journeyNodes(context, profile, Date.parse('2026-05-06T00:00:00')).find((n) => n.kind === '承诺到期')!.state).toBe('待兑现')
  })
  it('J3 nodes sorted; date shown once per day', () => {
    const kinds = journeyNodes(context, profile, 0).map((n) => n.kind)
    expect(kinds.slice(0, 2)).toEqual(['下单', '付款'])
    render(<ServiceJourney context={context} profile={profile} />)
    expect(screen.getAllByText('05/01')).toHaveLength(1)
  })
  it('J4 ignores profile of another conversation', () => {
    const kinds = journeyNodes(context, { ...profile, conversationId: 'S9' }).map((n) => n.kind)
    expect(kinds).not.toContain('情绪升级')
    expect(kinds).not.toContain('客服承诺')
  })
  it('J5 current contact uses first message time', () => {
    const node = journeyNodes({ ...context, firstAt: '2026-05-01T10:00:00' }, null).find((n) => n.kind === '本次进线')!
    expect(node.at).toBe('2026-05-07T17:32:00')
  })
})
