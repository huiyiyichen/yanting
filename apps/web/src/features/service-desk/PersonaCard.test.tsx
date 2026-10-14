/**
 * 画像卡（P1-2）。先列失败方式：
 * C1 按昵称聚合时没有“同昵称”标记，被误读为同一实名身份。
 * C2 消费者未自述肤质时仍显示肤质；自述后悬停看不到原话。
 * C3 承诺卡缺到期日或状态；已到期（due）没有风险色。
 * C4 已拒绝事项没有删除线样式，与关注混淆。
 * C5 情绪只靠颜色，没有“平稳/不满/激烈”文字。
 * C6 声纹没有可读的 aria-label 文字摘要。
 */
import { render, screen } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { describe, expect, it } from 'vitest'
import type { ConsumerProfileView } from '../../api/client'
import { PersonaCard } from './PersonaCard'

const base: ConsumerProfileView = {
  conversationId: 'S00059', alias: '魏h**', aggregation: 'buyer_alias',
  asOf: '2026-05-07T09:41:12Z',
  contacts: { withinThreeDays: 2, total: 2 },
  lastContact: { conversationId: 'S00005', at: '2026-05-05T04:08:51Z', scene: '退款迟迟不到账' },
  skin: null,
  memory: { concerns: [{ text: '退款到账时效', sourceRef: 'message:S00005:1' }],
    rejected: [{ text: '不想再叠面霜', sourceRef: 'message:S00059:2' }], tried: [], pending: [] },
  promises: [{ text: '若3个工作日内仍未到账，我们走线下打款直接补给您', madeAt: '2026-05-05T04:08:07Z',
    dueAt: '2026-05-08T15:59:59Z', status: 'pending', sourceRef: 'message:S00005:5', evidenceRef: null }],
  purchases: [],
  currentEmotion: 'angry', escalatedAt: '2026-05-07T09:34:34Z',
  emotionTrail: [
    { at: '2026-05-07T09:32:52Z', role: 'customer', level: 'dissatisfied', sourceRef: 'm1' },
    { at: '2026-05-07T09:33:39Z', role: 'operator', level: null, sourceRef: 'm2' },
    { at: '2026-05-07T09:34:34Z', role: 'customer', level: 'angry', sourceRef: 'm3' },
  ],
}

const mount = (profile: ConsumerProfileView) => render(<ConfigProvider><PersonaCard profile={profile} /></ConfigProvider>)

describe('PersonaCard', () => {
  it('C1 marks alias aggregation', () => {
    mount(base)
    expect(screen.getByText('同昵称')).toBeInTheDocument()
    expect(screen.getByText('进线 2 次')).toBeInTheDocument()
  })
  it('C2 shows skin only when self-reported, with the quote', () => {
    mount(base)
    expect(screen.queryByTestId('persona-skin')).toBeNull()
    mount({ ...base, skin: { text: '混合皮', sourceRef: 'm9', quote: '我其实更接近混合皮' } })
    expect(screen.getByTestId('persona-skin')).toHaveAttribute('title', '我其实更接近混合皮')
  })
  it('C3 promise card shows due date and status; due uses risk class', () => {
    const { container, unmount } = mount(base)
    expect(screen.getByText('05/08 待兑现')).toBeInTheDocument()
    unmount()
    const due = mount({ ...base, promises: [{ ...base.promises[0], status: 'due' }] })
    expect(due.container.querySelector('.yt-promise.is-due')).not.toBeNull()
    expect(container).toBeTruthy()
  })
  it('C4 rejected items are struck through', () => {
    mount(base)
    expect(screen.getByText('不想再叠面霜').closest('.yt-memory-tag')).toHaveClass('is-rejected')
  })
  it('C5 emotion has a text label', () => {
    mount(base)
    expect(screen.getByText('激烈')).toBeInTheDocument()
  })
  it('C6 voiceprint has a text summary', () => {
    mount(base)
    expect(screen.getByRole('img', { name: /消费者消息 2 条.*激烈 1/ })).toBeInTheDocument()
  })
})
