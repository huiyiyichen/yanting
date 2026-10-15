/**
 * 聊天头部单行 + AI 接待输入条（P1-1）。先列失败方式：
 * H1 头部仍分多行：风险标签、AI/人工切换、建工单、刷新不在同一个头部里。
 * H2 切到「人工」没有立即接管；切回「AI」未经确认就交还。
 * H3 AI 接待中仍显示可输入的回复框，或缺少「接管」入口；AI 回复中状态不可见。
 * H4 待复核风险与当前风险混为一谈（待复核需带前缀）；头像缺少当前情绪圆点。
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { ReceptionItem } from '../../api/client'
import { AiReceptionBar, ChatHead } from './ChatHead'

const item: ReceptionItem = {
  conversationId: 'c1', buyerAlias: '魏h**', title: 't', preview: '', updatedAt: '2026-05-07T10:00:00+00:00',
  dataSource: 'live', messageRevision: 1, unreadCount: 0, serviceMode: 'autonomous', modeRevision: 0,
  autoReplyStatus: 'idle', activeRiskTypes: ['complaint_risk'], reviewRiskTypes: ['response_wait'],
  currentEmotion: 'angry', riskLevel: 'high', waitThresholdSeconds: 120,
}
const head = (patch: Partial<ReceptionItem> = {}, onMode = vi.fn()) => {
  render(<MemoryRouter><ChatHead item={{ ...item, ...patch }} switching={false} onMode={onMode}
    onTicket={() => {}} onRefresh={() => {}} /></MemoryRouter>)
  return onMode
}

describe('ChatHead', () => {
  it('H1 H4 one header row with everything', () => {
    head()
    const header = screen.getByRole('banner')
    for (const name of ['建工单', '刷新会话']) expect(within(header).getByRole('button', { name })).toBeTruthy()
    expect(within(header).getByRole('radiogroup', { name: '接待方式' })).toBeTruthy()
    expect(within(header).getByRole('link', { name: '查看当前投诉风险' })).toBeTruthy()
    expect(within(header).getByText(/待复核 · /)).toBeTruthy()
    expect(header.querySelector('.yt-emotion-dot.is-angry')).toBeTruthy()
  })
  it('H2 manual immediately, AI after confirm', async () => {
    const user = userEvent.setup()
    const onMode = head()
    await user.click(screen.getByText('人工'))
    expect(onMode).toHaveBeenCalledWith('operator_assisted')
  })
  it('H2 back to AI needs confirm', async () => {
    const user = userEvent.setup()
    const onMode = head({ serviceMode: 'operator_assisted' })
    await user.click(screen.getByText('AI'))
    expect(onMode).not.toHaveBeenCalled()
    await user.click(await screen.findByRole('button', { name: /恢\s?复/ }))
    expect(onMode).toHaveBeenCalledWith('autonomous')
  })
})

describe('AiReceptionBar', () => {
  it('H3 shows status and takeover, no textbox', async () => {
    const user = userEvent.setup()
    const take = vi.fn()
    const { rerender } = render(<AiReceptionBar replying={false} switching={false} onTakeOver={take} />)
    expect(screen.getByText('AI 接待中')).toBeTruthy()
    expect(screen.queryByRole('textbox')).toBeNull()
    await user.click(screen.getByRole('button', { name: '接管会话' }))
    expect(take).toHaveBeenCalled()
    rerender(<AiReceptionBar replying switching={false} onTakeOver={take} />)
    expect(screen.getByText('AI 回复中')).toBeTruthy()
  })
})
