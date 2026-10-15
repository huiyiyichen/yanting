/**
 * 插件「档案」页：这个客户是谁（跨会话），不重复左侧聊天与辅助页内容。
 * F1 无上下文时崩溃或渲染空标题；
 * F2 金额按分显示错误、累计实付把同一订单算两次；
 * F3 历史进线混入当前会话，或时间不按北京时间；
 * F4 服务记忆空类别也渲染标题占位；
 * F5 工单不能跳转详情、不能新建；
 * F6 有订单时仍把公开商品当订单列出。
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ArchivePanel } from './ArchivePanel'
import type { ConsumerServiceContextView, ServiceMemoryView, TicketView } from '../../api/client'

const order = {
  sourceRecordId: 'r1', orderId: 'O-1', conversationId: 'S1', buyerAlias: '甲', productName: '粉底液', sku: 'SKU1',
  quantity: 1, paidAmountMinor: 25900, currency: 'CNY', sourceStatus: '已发货', orderedAt: '2026-05-01T10:00:00',
  carrier: '顺丰', city: '上海',
}
const context = {
  datasetId: 'd', batchId: 'b', conversationId: 'S1', buyerAlias: '甲', buyerAliases: ['甲', '甲甲'],
  orders: [order, { ...order }, { ...order, sourceRecordId: 'r2', orderId: 'O-2', paidAmountMinor: 9900, productName: '卸妆水' }],
  workOrders: [], timeline: [], products: [{ sku: 'SKU9', name: '公开商品', unitPriceMinor: 100, sourceRecordIds: [] }],
  historyServices: [
    { conversationId: 'S1', firstAt: '2026-05-02T09:00:00Z', latestCustomerMessage: '当前会话原话', latestStaffMessage: '', relation: 'historical' },
    { conversationId: 'S0', firstAt: '2026-04-30T09:38:00Z', latestCustomerMessage: '上次包装破损', latestStaffMessage: '', relation: 'same_order', sameTopic: true },
  ],
} as unknown as ConsumerServiceContextView
const memory = { conversationId: 'S1', revision: 1, stale: false, verified: true,
  items: [{ category: 'concern', sourceRef: 's1', quote: '担心过敏', label: '过敏' }], sources: [] } as unknown as ServiceMemoryView
const tickets = [{ ticketId: 'BH1', workOrderType: 'refund', status: 'open' }] as unknown as TicketView[]

describe('ArchivePanel', () => {
  it('无上下文显示空态', () => {
    render(<ArchivePanel context={null} memory={null} tickets={[]} onOpenTicket={vi.fn()} onNewTicket={vi.fn()} />)
    expect(screen.getByText('暂无档案')).toBeInTheDocument()
  })
  it('身份条、购买、历史进线、记忆、工单', async () => {
    const open = vi.fn(), create = vi.fn()
    render(<ArchivePanel context={context} memory={memory} tickets={tickets} onOpenTicket={open} onNewTicket={create} />)
    const head = screen.getByRole('region', { name: '消费者服务档案' })
    expect(within(head).getByText('甲', { selector: 'strong' })).toBeInTheDocument()
    expect(within(head).getByText('甲甲')).toBeInTheDocument()
    expect(within(head).getByText('¥358.00')).toBeInTheDocument()
    const buys = screen.getByRole('region', { name: '购买记录' })
    expect(within(buys).getAllByRole('listitem')).toHaveLength(2)
    expect(within(buys).queryByText('公开商品')).toBeNull()
    const history = screen.getByRole('region', { name: '历史进线' })
    expect(within(history).queryByText('当前会话原话')).toBeNull()
    expect(within(history).getByText('上次包装破损')).toBeInTheDocument()
    expect(within(history).getByText('04/30 17:38')).toBeInTheDocument()
    expect(within(history).getByText('同一诉求')).toBeInTheDocument()
    expect(screen.getByText('1 次历史进线')).toBeInTheDocument()
    const mem = screen.getByRole('region', { name: '服务记忆' })
    expect(within(mem).getByText('担心过敏')).toBeInTheDocument()
    expect(within(mem).queryByText('已尝试措施')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /BH1/ }))
    expect(open).toHaveBeenCalledWith('BH1')
    await userEvent.click(screen.getByRole('button', { name: /新建工单/ }))
    expect(create).toHaveBeenCalled()
  })
  it('无订单时列出本会话商品', () => {
    render(<ArchivePanel context={{ ...context, orders: [] }} memory={null} tickets={[]} onOpenTicket={vi.fn()} onNewTicket={vi.fn()} />)
    const buys = screen.getByRole('region', { name: '购买记录' })
    expect(within(buys).getByText('公开商品')).toBeInTheDocument()
    expect(within(buys).getByText('SKU9')).toBeInTheDocument()
  })
})
