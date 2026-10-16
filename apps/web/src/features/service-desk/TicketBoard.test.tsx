/**
 * 工单看板（P2-3）。
 * B1 等待客户与等待内部分散两列或丢失，“等待反馈”列不全；
 * B2 看板绕开筛选，显示与列表不同的工单；
 * B3 到期工单埋在列中间，没有标记；
 * B4 点卡片打不开详情；看板误把拖拽当状态修改（状态只能在详情里带版本号保存）。
 */
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { TicketView } from '../../api/client'
import { TicketBoard } from './TicketBoard'

const now = Date.parse('2026-10-16T06:00:00Z')
const t = (ticketId: string, patch: Partial<TicketView>): TicketView => ({
  ticketId, title: ticketId, conversationId: 'S1', buyerAlias: '消费者甲', workOrderType: 'logistics',
  status: 'pending', priority: 'normal', assignee: 'G001', createdAt: '2026-10-15T00:00:00Z',
  updatedAt: '2026-10-15T00:00:00Z', revision: 1, ...patch,
})

describe('TicketBoard', () => {
  const rows = [
    t('A', { status: 'pending', dueAt: '2026-10-20T00:00:00Z' }),
    t('B', { status: 'pending', dueAt: '2026-10-16T01:00:00Z' }),
    t('C', { status: 'waiting_customer' }), t('D', { status: 'waiting_internal' }),
    t('E', { status: 'in_progress' }), t('F', { status: 'resolved' }),
  ]
  it('按状态分四列，等待客户与等待内部同列', () => {
    render(<TicketBoard rows={rows} now={now} onOpen={() => {}} />)
    const column = (name: string) => within(screen.getByRole('region', { name }))
    expect(column('待受理').getAllByRole('button').map((b) => b.dataset.ticket)).toEqual(['B', 'A'])
    expect(column('等待反馈').getAllByRole('button').map((b) => b.dataset.ticket).sort()).toEqual(['C', 'D'])
    expect(column('处理中').getAllByRole('button')).toHaveLength(1)
    expect(column('已完成').getAllByRole('button')).toHaveLength(1)
    expect(column('待受理').getByText('已到期')).toBeInTheDocument()
  })
  it('只显示传入的筛选结果，点卡片打开详情', () => {
    const onOpen = vi.fn()
    render(<TicketBoard rows={rows.slice(0, 1)} now={now} onOpen={onOpen} />)
    expect(screen.getAllByRole('button')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button'))
    expect(onOpen).toHaveBeenCalledWith('A')
    expect(screen.getByRole('button')).not.toHaveAttribute('draggable', 'true')
  })
})
