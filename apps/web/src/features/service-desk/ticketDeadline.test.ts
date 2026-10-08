import { describe, expect, it } from 'vitest'
import { ticketDeadline } from './ticketDeadline'

describe('工单跟进期限', () => {
  const now = Date.parse('2026-10-02T04:00:00Z')
  const ticket = { status: 'pending' as const }
  it('到期边界、24小时边界和未来期限使用一致口径', () => {
    expect(ticketDeadline({ ...ticket, dueAt: '2026-10-02T04:00:00Z' }, now)).toBe('overdue')
    expect(ticketDeadline({ ...ticket, dueAt: '2026-10-03T04:00:00Z' }, now)).toBe('soon')
    expect(ticketDeadline({ ...ticket, dueAt: '2026-10-03T04:00:01Z' }, now)).toBe('scheduled')
  })
  it('完成工单、无期限和无效时间不进入待办提醒', () => {
    expect(ticketDeadline({ status: 'resolved', dueAt: '2026-10-01T04:00:00Z' }, now)).toBe('none')
    expect(ticketDeadline(ticket, now)).toBe('none')
    expect(ticketDeadline({ ...ticket, dueAt: 'invalid' }, now)).toBe('none')
  })
  it('同一时间的不同表示和时间自然推进不改变规则', () => {
    expect(ticketDeadline({ ...ticket, dueAt: '2026-10-02T12:00:00+08:00' }, now)).toBe('overdue')
    const future = { ...ticket, dueAt: '2026-10-02T04:01:00Z' }
    expect(ticketDeadline(future, now)).toBe('soon')
    expect(ticketDeadline(future, now + 60000)).toBe('overdue')
  })
})
