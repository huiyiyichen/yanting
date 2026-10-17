/**
 * 风险看板总览（P1-6）。先列失败方式：
 * V1 事件数与信号数混在一个数字里。
 * V2 情绪分布柱高不按数量（中线以上不满+激烈，中线以下平稳），或缺少文字摘要。
 * V3 商品线索出现质量结论文字（如“质量问题”“同批次”），只允许计数。
 * V4 点击类型条不筛选下方列表（onFilterType 未带类型）。
 * V5 点击高风险会话标记不打开对应会话筛选（onFilterConversation 未带会话号）。
 * V7 大声纹柱子过多挤成一团（1 小时一根 × 7 天 = 112 根）：总数应控制在约 60 根内；
 *    范围切换压住图例；标题日期范围与图上显示的天数不一致。
 * V6 商品线索不能展开到订单与会话（反馈 ⑤）；展开后不按批次分组。
 */
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { describe, expect, it, vi } from 'vitest'
import type { ProductClueView, RiskOverviewView } from '../../api/client'
import { RiskOverviewPanel, mergeStep } from './RiskOverviewPanel'

const overview: RiskOverviewView = {
  scope: 'official',
  counts: { events: 72, signals: 92, pending: 56, high: 18, emotionEscalation: 13, adverseReaction: 10 },
  levels: { high: 25, medium: 59, low: 8 },
  types: { repeated_contact: 50, emotion_escalation: 13, adverse_reaction: 10 },
  hourly: [
    { date: '2026-05-05', hour: 21, calm: 4, dissatisfied: 6, angry: 3 },
    { date: '2026-05-05', hour: 22, calm: 2, dissatisfied: 1, angry: 0 },
  ],
  highRiskMarkers: [{ date: '2026-05-05', hour: 21, conversationId: 'S00059', alias: '魏h**', types: ['complaint_risk'] }],
  customerMessages: 16, negativeShare: 0.625, emotionSource: 'rule',
}
const clues: ProductClueView[] = [{
  productName: '测试B5多效修护面膜20片', adverseReactions: 3, medicalVisits: 1, batches: ['26A05', '26A18', '未记录'],
  relatedTickets: 4, otherTickets: 1, abnormalReturns: 0, score: 15, workOrderIds: ['W1'],
  cases: [
    { workOrderId: 'W1', workOrderType: 'adverse_reaction', orderId: '6920156290763740456', conversationId: 'S00012', buyerAlias: '半d**', batch: '26A05', createdAt: '2026-05-06T10:00:00+08:00' },
    { workOrderId: 'W2', workOrderType: 'return_refund', orderId: null, conversationId: 'S00020', buyerAlias: '雷**', batch: null, createdAt: '2026-05-07T10:00:00+08:00' },
  ],
}]

function mount(props = {}) {
  const handlers = { onFilterType: vi.fn(), onFilterConversation: vi.fn() }
  render(<MemoryRouter><ConfigProvider><RiskOverviewPanel overview={overview} clues={clues} {...handlers} {...props} /></ConfigProvider></MemoryRouter>)
  return handlers
}

describe('RiskOverviewPanel', () => {
  it('V1 shows events and signals separately', () => {
    mount()
    expect(screen.getByLabelText('风险事件')).toHaveTextContent('72')
    expect(screen.getByLabelText('风险信号')).toHaveTextContent('92')
  })
  it('V2 distribution has a text summary with counts', () => {
    mount()
    expect(screen.getByRole('img', { name: /消费者消息 16 条.*负面 10 条/ })).toBeInTheDocument()
  })
  it('V3 product clue has counts only', () => {
    mount()
    const card = screen.getByText('测试B5多效修护面膜20片').closest('li')!
    expect(card).toHaveTextContent('不良反应 3')
    expect(card).toHaveTextContent('就医 1')
    expect(card.textContent).not.toMatch(/质量问题|同批次|聚集/)
  })
  it('V4 type bar filters the list', () => {
    const handlers = mount()
    fireEvent.click(screen.getByRole('button', { name: /不良反应 10/ }))
    expect(handlers.onFilterType).toHaveBeenCalledWith('adverse_reaction')
  })
  it('V5 high-risk marker filters to its conversation', () => {
    const handlers = mount()
    fireEvent.click(screen.getByRole('button', { name: /魏h\*\*/ }))
    expect(handlers.onFilterConversation).toHaveBeenCalledWith('S00059')
  })
  it('V6 点商品展开按批次分组的工单、订单与会话，点会话筛选队列', async () => {
    const handlers = mount()
    fireEvent.click(screen.getByRole('button', { name: '展开订单 测试B5多效修护面膜20片' }))
    const batch = await screen.findByRole('region', { name: '批次 26A05' })
    expect(within(batch).getByText('订单 …0456')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '其他工单' })).toHaveTextContent('无订单')
    fireEvent.click(within(batch).getByRole('button', { name: '半d** · S00012' }))
    expect(handlers.onFilterConversation).toHaveBeenCalledWith('S00012')
  })
  it('V7 柱子总数不超过 60：7 天 16 小时按 2 小时合并，19 天按 6 小时', () => {
    expect(mergeStep(7, 16)).toBe(2)
    expect(mergeStep(19, 16)).toBe(6)
    expect(mergeStep(1, 16)).toBe(1)
  })
})

