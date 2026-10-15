/**
 * 插件辅助页的诉求 / 下一步 / 更多依据（概念稿 yanting-concept-plugin）。先列失败方式：
 * A1 没有诉求时仍渲染空的“诉求”行。
 * A2 主诉求与其他诉求视觉一致，看不出主次；重复诉求出现两次。
 * A3 下一步只能读不能勾；勾选后刷新/切回会话丢失。
 * A4 已完成步骤仍排在前面，干扰未完成事项。
 * A5 依据折叠没有数量；展开状态无 aria-expanded；数量为 0 的类别仍占一行（知识依据除外，需显示“0”提示依据不足）。
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { EvidenceFolds, IntentRow, NextSteps } from './AssistBlocks'

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
