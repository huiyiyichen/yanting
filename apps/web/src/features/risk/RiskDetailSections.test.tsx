/**
 * 风险详情分节。先列失败方式：
 * D1 情绪轨迹缺失或无可读描述；升级（升到激烈）的那一跳不标出。
 * D2 触发依据丢失触发词标记；同类型多条原话拆成多个气泡且无时间段。
 * D3 无原话时空白，而不是展示触发摘要。
 * D4 关联记录缺承诺/订单/工单，或已兑现承诺仍显示；工单行不可点开。
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ConsumerProfileView, RiskIncidentDetailView } from '../../api/client'
import { RiskEmotionTrack, RiskLinks, RiskTriggers, linkedRecords } from './RiskDetailSections'

const emo = (id: string, at: string, emotion: 'calm' | 'dissatisfied' | 'angry') =>
  ({ messageId: id, conversationId: 'S1', occurredAt: at, body: id, emotion, triggerFactors: [] })

describe('RiskDetailSections', () => {
  it('D1 track has label and marks escalation', () => {
    const { container } = render(<RiskEmotionTrack history={[emo('a', '2026-05-07T17:32:00', 'calm'),
      emo('b', '2026-05-07T17:35:00', 'dissatisfied'), emo('c', '2026-05-07T17:38:00', 'angry')]} />)
    expect(screen.getByRole('img', { name: '情绪轨迹：平稳到激烈，3 条消息' })).toBeInTheDocument()
    expect(screen.getByText('升级')).toBeInTheDocument()
    expect(container.querySelectorAll('circle.yt-etrack-dot')).toHaveLength(3)
  })
  it('D2 merges quotes with range and keeps highlights', () => {
    render(<RiskTriggers onOpen={vi.fn()} rows={[{ key: 'c', type: '投诉风险', high: true, summary: 's', quotes: [
      { ref: 'm1', kind: 'customer_message', label: '', body: '我要去平台投诉', occurredAt: '2026-05-07T17:36:00', conversationId: 'S1', highlights: [{ start: 5, end: 7, kind: 'complaint' as const }] },
      { ref: 'm2', kind: 'customer_message', label: '', body: '退款', occurredAt: '2026-05-07T17:38:00', conversationId: 'S1', highlights: [] },
    ] }]} />)
    expect(screen.getByText('17:36 → 17:38', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('投诉', { selector: 'mark' })).toBeInTheDocument()
    expect(document.querySelectorAll('.yt-ev-quote')).toHaveLength(1)
  })
  it('D3 falls back to summary', () => {
    render(<RiskTriggers onOpen={vi.fn()} rows={[{ key: 'r', type: '重复进线', high: false, summary: '3 天内第 3 次进线', quotes: [] }]} />)
    expect(screen.getByText('3 天内第 3 次进线')).toBeInTheDocument()
  })
  it('D4 linked records: open promise, order, clickable ticket', () => {
    const open = vi.fn()
    const detail = { contexts: [{ orders: [{ orderId: 'O1', productName: '玻尿酸面膜', paidAmountMinor: 8900, carrier: '中通', shippedAt: '2026-05-02' }] }],
      tickets: [{ ticketId: 'T1', title: '空包退款', assignee: '王', status: 'in_progress' }] } as unknown as RiskIncidentDetailView
    const profile = { promises: [
      { text: '48 小时内回复', madeAt: '2026-05-07T17:40:00', dueAt: '2026-05-09T17:40:00', status: 'pending', sourceRef: 'message:S1:m9' },
      { text: '已补发', madeAt: '2026-05-03T10:00:00', dueAt: '2026-05-04T10:00:00', status: 'fulfilled', sourceRef: 'message:S0:m1' },
    ] } as unknown as ConsumerProfileView
    render(<RiskLinks rows={linkedRecords(detail, profile, open)} />)
    expect(screen.getByText('05/07 承诺：48 小时内回复')).toBeInTheDocument()
    expect(screen.queryByText(/已补发/)).toBeNull()
    expect(screen.getByText('玻尿酸面膜')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /空包退款/ }))
    expect(open).toHaveBeenCalledWith('T1')
  })
})
