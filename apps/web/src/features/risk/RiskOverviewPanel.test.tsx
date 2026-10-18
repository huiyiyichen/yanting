/**
 * 风险看板总览（P1-6）。先列失败方式：
 * V1 事件数与信号数混在一个数字里。
 * V2 情绪分布柱高不按数量（中线以上不满+激烈，中线以下平稳），或缺少文字摘要。
 * V3 商品线索出现质量结论文字（如“质量问题”“同批次”），只允许计数。
 * V4 点击类型条不筛选下方列表（onFilterType 未带类型）。
 * V5 点击高风险会话标记不打开对应会话筛选（onFilterConversation 未带会话号）。
 * V7 大声纹柱子过多挤成一团（1 小时一根 × 7 天 = 112 根）：总数应控制在约 60 根内；
 *    范围切换压住图例；标题日期范围与图上显示的天数不一致。
 * V8 声纹图上常驻峰值文字（“05/07 16时起 负面 10”）压在柱子中间：不应常驻，只在悬停提示里出现。
 * V9 X-1 框选：在主图拖动选时间段不回调 onRange；双击不清除；缩略条点某天不把 7 天写成区间；
 *    方向键不平移；有区间时没有清除入口；悬停列表行时对应菱形不放大。
 * V9 X-1 框选：在主图拖动选时间段不回调 onRange；双击不清除；缩略条点某天不把 7 天写成区间；
 *    方向键不平移；有区间时没有清除入口；悬停列表行时对应菱形不放大。
 * V6 商品线索不能展开到订单与会话（反馈 ⑤）；展开后不按批次分组。
 * R1 风险页反馈 1：仍画 ≈ 断轴；R3 反馈 3：没有 近7天/全部/自选。
 * R4 用户反馈 10-18 #4：自选仍是抽象的缩略条，应改为日期区间选择（显示所选起止日期）。
 */
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { describe, expect, it, vi } from 'vitest'
import type { ProductClueView, RiskOverviewView } from '../../api/client'
import { RiskOverviewPanel, mergeStep } from './RiskOverviewPanel'

const overview: RiskOverviewView = {
  scope: 'official',
  counts: { events: 72, signals: 92, pending: 56, pendingHigh: 12, high: 18, emotionEscalation: 13, adverseReaction: 10 },
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
  it('V8 声纹上没有常驻的峰值文字', () => {
    const { container } = render(<MemoryRouter><ConfigProvider><RiskOverviewPanel overview={overview} clues={clues} onFilterType={vi.fn()} onFilterConversation={vi.fn()} /></ConfigProvider></MemoryRouter>)
    expect(container.querySelector('.yt-dist svg')?.textContent).not.toMatch(/负面/)
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
  it('V9 框选、缩略条、方向键、清除与悬停联动', () => {
    const many: RiskOverviewView = { ...overview, hourly: Array.from({ length: 12 }, (_, i) => (
      { date: `2026-05-${String(i + 1).padStart(2, '0')}`, hour: 10, calm: 1, dissatisfied: i < 7 ? 2 : 0, angry: 0 })),
    highRiskMarkers: [{ date: '2026-05-10', hour: 10, conversationId: 'S1', alias: '甲', types: [] }] }
    const onRange = vi.fn()
    const { container, rerender } = render(<MemoryRouter><ConfigProvider><RiskOverviewPanel overview={many} clues={[]}
      onFilterType={vi.fn()} onFilterConversation={vi.fn()} onRange={onRange} hotConversation="S1" /></ConfigProvider></MemoryRouter>)
    expect(screen.getByLabelText('甲 S1')).toHaveClass('is-hot')
    const svg = container.querySelector('.yt-dist svg')!
    svg.getBoundingClientRect = () => ({ left: 0, width: 1080, top: 0, height: 214, right: 1080, bottom: 214, x: 0, y: 0, toJSON: () => ({}) })
    fireEvent.mouseDown(svg, { clientX: 5 }); fireEvent.mouseMove(svg, { clientX: 1075 }); fireEvent.mouseUp(svg)
    expect(onRange).toHaveBeenLastCalledWith({ from: '2026-05-06', to: '2026-05-12' })
    fireEvent.doubleClick(svg)
    expect(onRange).toHaveBeenLastCalledWith(null)
    expect(screen.queryByRole('group', { name: '声纹缩略条' })).toBeNull()  // R3 近 7 天不显示缩略条
    expect(screen.queryByLabelText('断档')).toBeNull()  // R1 不画断轴
    fireEvent.click(screen.getByRole('button', { name: '自选' }))
    expect(screen.queryByRole('group', { name: '声纹缩略条' })).toBeNull()
    expect(container.querySelector('.yt-dist-picker')).not.toBeNull()
    rerender(<MemoryRouter><ConfigProvider><RiskOverviewPanel overview={many} clues={[]} onFilterType={vi.fn()}
      onFilterConversation={vi.fn()} onRange={onRange} range={{ from: '2026-05-03', to: '2026-05-09' }} /></ConfigProvider></MemoryRouter>)
    const inputs = container.querySelectorAll<HTMLInputElement>('.yt-dist-picker input')
    expect([...inputs].map((input) => input.value)).toEqual(['05/03', '05/09'])
  })
})

