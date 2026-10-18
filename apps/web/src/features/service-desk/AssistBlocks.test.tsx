/**
 * 插件辅助页的诉求 / 下一步 / 更多依据（概念稿 yanting-concept-plugin）。先列失败方式：
 * A1 没有诉求时仍渲染空的“诉求”行。
 * A2 主诉求与其他诉求视觉一致，看不出主次；重复诉求出现两次。
 * A3 下一步只能读不能勾；勾选后刷新/切回会话丢失。
 * A4 已完成步骤仍排在前面，干扰未完成事项。
 * A5 依据折叠没有数量；展开状态无 aria-expanded；数量为 0 的类别仍占一行（知识依据除外，需显示“0”提示依据不足）。
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { EvidenceFolds, HandoffSummary, IntentRow, NextSteps } from './AssistBlocks'

beforeEach(() => localStorage.clear())

describe('AssistBlocks', () => {
  it('A1 no intent renders nothing', () => {
    const { container } = render(<IntentRow items={[]} missing={[]} />)
    expect(container).toBeEmptyDOMElement()
  })
  it('A2 primary intent is marked and duplicates collapse', () => {
    render(<IntentRow primary="仅退款" items={['仅退款', '空包裹', '空包裹']} missing={['订单号']} />)
    expect(screen.getByText('仅退款')).toHaveClass('ink')
    expect(screen.getAllByText('空包裹')).toHaveLength(1)
    expect(screen.getByText('待确认 订单号')).toHaveClass('mid')
  })
  it('A3 steps can be checked and survive remount', () => {
    const { unmount } = render(<NextSteps scope="S1:h1" steps={['核对称重', '跟进退款']} />)
    fireEvent.click(screen.getByRole('checkbox', { name: '核对称重' }))
    unmount()
    render(<NextSteps scope="S1:h1" steps={['核对称重', '跟进退款']} />)
    expect(screen.getByRole('checkbox', { name: '核对称重' })).toBeChecked()
    expect(screen.getByText('1/2')).toBeInTheDocument()
  })
  it('A4 done steps sink to the bottom', () => {
    render(<NextSteps scope="S2:h1" steps={['甲', '乙']} />)
    fireEvent.click(screen.getByRole('checkbox', { name: '甲' }))
    const labels = screen.getAllByRole('checkbox').map((box) => box.parentElement?.textContent)
    expect(labels).toEqual(['乙', '甲'])
  })
  it('A5 folds show counts, expand in place, hide empty non-knowledge', () => {
    render(<EvidenceFolds folds={[
      { key: 'knowledge', label: '知识依据', count: 0, icon: 'knowledge', body: '依据不足' },
      { key: 'orders', label: '订单与物流', count: 1, icon: 'order', body: '订单 0707' },
      { key: 'tickets', label: '售后工单', count: 0, icon: 'ticket', body: 'x' },
    ]} />)
    expect(screen.queryByText('售后工单')).toBeNull()
    const order = screen.getByRole('button', { name: /订单与物流/ })
    expect(order).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(order)
    expect(order).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('订单 0707')).toBeInTheDocument()
  })
})

/**
 * 交接摘要（重新保留，改为 AI 总结）：
 * H1 无模型结果时拼接聊天原句；H2 有 service_summary 时仍显示“待生成”或不显示正文。
 * H3 摘要不能单独生成：没有“生成摘要”胶囊按钮，或点击后没调摘要生成（用户反馈 10-18 #1，与生成回复分开）。
 */
describe('HandoffSummary', () => {
  it('H1 H3 shows a 生成摘要 capsule without AI summary', () => {
    const onGenerate = vi.fn()
    render(<HandoffSummary summary={null} busy={false} stale={false} onGenerate={onGenerate} />)
    const region = screen.getByRole('region', { name: '交接摘要' })
    expect(region.querySelector('p')).toBeNull()
    const button = screen.getByRole('button', { name: '生成摘要' })
    expect(button).toHaveClass('yt-gen-pill')
    fireEvent.click(button)
    expect(onGenerate).toHaveBeenCalledTimes(1)
  })
  it('H3 busy shows 生成中 and stale offers 更新摘要', () => {
    const { rerender } = render(<HandoffSummary summary={null} busy stale={false} onGenerate={vi.fn()} />)
    expect(screen.getByRole('region', { name: '交接摘要' })).toHaveTextContent('生成中')
    rerender(<HandoffSummary summary="旧摘要" busy={false} stale onGenerate={vi.fn()} />)
    expect(screen.getByRole('button', { name: '更新摘要' })).toBeInTheDocument()
  })
  it('H2 shows the AI summary', () => {
    render(<HandoffSummary summary=" 空包投诉，已建退款工单待财务审核，客户催促到账。 " busy={false} stale={false} onGenerate={vi.fn()} />)
    expect(screen.getByText('空包投诉，已建退款工单待财务审核，客户催促到账。')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '生成摘要' })).toBeNull()
  })
})
