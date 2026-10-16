/**
 * 工单列表排序与筛选（替代看板，效率优先）。先列失败方式：
 * F1 已到期的工单排在普通工单之后，处理人要往下翻才看到；
 * F2 同为到期状态时，紧急的排在普通之后；同级时期限晚的在前；
 * F3 已完成组仍按期限排，最近完成的反而沉底；
 * F4 快捷筛选叠加时变成“或”，“我的 + 到期”混进别人的工单；
 * F5 “我的/待分配/到期”混入已完成工单；
 * F6 期限文案只给日期，看不出超期多久/还剩多久；无期限或已完成却显示倒计时；
 * F8 混合状态整体排序时比较不一致（已完成与未完成用不同规则），导致组内高优先级被打乱；
 * F7 等待客户与等待内部被分到两组。
 */
import { describe, expect, it } from 'vitest'
import type { TicketView } from '../../api/client'
import { compareTickets, dueText, groupOf, matchesQuick } from './ticketList'

const now = new Date('2026-10-16T10:00:00+08:00').getTime()
const h = (n: number) => new Date(now + n * 3600_000).toISOString()
const t = (id: string, patch: Partial<TicketView> = {}): TicketView => ({
  ticketId: id, title: id, conversationId: 'S1', buyerAlias: '甲', workOrderType: 'logistics', status: 'pending',
  priority: 'normal', assignee: 'G001', createdAt: h(-48), updatedAt: h(-10), revision: 1, ...patch,
})
const order = (rows: TicketView[]) => [...rows].sort((a, b) => compareTickets(a, b, now)).map((r) => r.ticketId)

describe('compareTickets', () => {
  it('F1/F2 到期优先，再看优先级与期限', () => {
    expect(order([
      t('无期限'), t('三天后', { dueAt: h(72) }), t('即将', { dueAt: h(3) }),
      t('超期普通', { dueAt: h(-5) }), t('超期紧急', { dueAt: h(-1), priority: 'urgent' }), t('超期更早', { dueAt: h(-9) }),
    ])).toEqual(['超期紧急', '超期更早', '超期普通', '即将', '三天后', '无期限'])
  })
  it('F3 已完成按最近更新', () => {
    expect(order([t('旧', { status: 'resolved', updatedAt: h(-30), dueAt: h(-50) }), t('新', { status: 'resolved', updatedAt: h(-1) })]))
      .toEqual(['新', '旧'])
  })
})

it('F8 混合状态排序稳定：先分组，组内高优先级在前', () => {
  expect(order([
    t('普通新', { updatedAt: h(-1) }), t('完成', { status: 'resolved', updatedAt: h(-2) }),
    t('普通旧', { updatedAt: h(-3) }), t('完成旧', { status: 'resolved', updatedAt: h(-4) }), t('高', { priority: 'high', updatedAt: h(-5) }),
    t('等待', { status: 'waiting_internal' }),
  ])).toEqual(['高', '普通新', '普通旧', '等待', '完成', '完成旧'])
})

describe('matchesQuick', () => {
  const rows = [t('我的到期', { dueAt: h(-1) }), t('我的不急'), t('别人到期', { assignee: 'G002', dueAt: h(-1) }),
    t('无人', { assignee: '' }), t('我的已完成', { status: 'resolved', dueAt: h(-1) })]
  const pick = (quick: Parameters<typeof matchesQuick>[1]) => rows.filter((r) => matchesQuick(r, quick, 'G001', now)).map((r) => r.ticketId)
  it('F4 叠加为与', () => expect(pick(['mine', 'due'])).toEqual(['我的到期']))
  it('F5 不含已完成', () => {
    expect(pick(['mine'])).toEqual(['我的到期', '我的不急'])
    expect(pick(['unassigned'])).toEqual(['无人'])
    expect(pick([])).toHaveLength(5)
  })
})

describe('dueText', () => {
  it('F6 超期/还剩，其余为空', () => {
    expect(dueText({ dueAt: h(-26), status: 'pending' }, now)).toBe('超期 26 小时')
    expect(dueText({ dueAt: h(-72), status: 'pending' }, now)).toBe('超期 3 天')
    expect(dueText({ dueAt: new Date(now + 40 * 60000).toISOString(), status: 'pending' }, now)).toBe('还剩 40 分钟')
    expect(dueText({ dueAt: h(72), status: 'pending' }, now)).toBe('')
    expect(dueText({ dueAt: h(-1), status: 'resolved' }, now)).toBe('')
    expect(dueText({ dueAt: null, status: 'pending' }, now)).toBe('')
  })
})

it('F7 等待合并', () => {
  expect(groupOf('waiting_customer')).toBe('waiting')
  expect(groupOf('waiting_internal')).toBe('waiting')
})
