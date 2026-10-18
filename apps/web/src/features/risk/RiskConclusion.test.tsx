/**
 * 风险结论（反馈 10-18 #2）失败方式：
 * F1 业务事实行（无原话）点击没反应；F2 历史信号胶囊仍占位；F3 行内工具按钮误触发跳转；
 * F4 回放找不到对应消息（无 messageId 时按信号类型/时间兜底）。
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RiskConclusion } from './RiskConclusion'
import { resolveFocusMessage } from './ConversationReplay'

const rows = [
  { key: 'a', level: 'high', type: '不良反应', text: '工单 BLFY61738711 已登记', at: '2026-10-10T02:00:00Z',
    jump: { conversationId: 'c1', messageId: '', riskType: 'adverse_reaction', at: '2026-10-10T02:00:00Z' }, state: null,
    tools: <button type="button">信号操作</button> },
  { key: 'b', level: 'medium', type: '投诉风险', text: '资料给你，咋赔偿说个方案', jump: { conversationId: 'c1', messageId: 'm2' }, state: '当前触发' },
]

describe('RiskConclusion', () => {
  it('整行可点击并带兜底提示跳转，历史信号不显示胶囊', () => {
    const onJump = vi.fn()
    render(<RiskConclusion rows={rows} onJump={onJump} />)
    fireEvent.click(screen.getByRole('button', { name: '跳到对话回放 不良反应' }))
    expect(onJump).toHaveBeenCalledWith('c1', '', { riskType: 'adverse_reaction', at: '2026-10-10T02:00:00Z' })
    fireEvent.keyDown(screen.getByRole('button', { name: '跳到对话回放 投诉风险' }), { key: 'Enter' })
    expect(onJump).toHaveBeenLastCalledWith('c1', 'm2', { riskType: undefined, at: undefined })
    expect(screen.queryByText('历史信号')).toBeNull()
    expect(screen.getByText('当前触发')).toBeInTheDocument()
    onJump.mockClear()
    fireEvent.click(screen.getByText('信号操作'))
    expect(onJump).not.toHaveBeenCalled()
  })

  it('回放定位：已知消息优先，其次信号类型、时间最近、最后一条客户消息', () => {
    const notes = [
      { messageId: 'm1', role: 'customer', at: '2026-10-10T01:00:00Z', body: 'a', signals: [] },
      { messageId: 'm2', role: 'operator', at: '2026-10-10T02:01:00Z', body: 'b' },
      { messageId: 'm3', role: 'customer', at: '2026-10-10T03:00:00Z', body: 'c', signals: ['complaint_risk'] },
    ] as never
    expect(resolveFocusMessage(notes, 'm1', { riskType: 'complaint_risk' })).toBe('m1')
    expect(resolveFocusMessage(notes, '', { riskType: 'complaint_risk' })).toBe('m3')
    expect(resolveFocusMessage(notes, '', { riskType: 'adverse_reaction', at: '2026-10-10T02:00:00Z' })).toBe('m2')
    expect(resolveFocusMessage(notes, '', { riskType: 'adverse_reaction' })).toBe('m3')
    expect(resolveFocusMessage(notes, '', undefined)).toBe('')
  })
})
