/**
 * 客服队列项（P1-1）。先列失败方式：
 * Q1 等待超过阈值时不显示红色等待时长，或未超阈值也显示（口径须用后端 waitingSince + 阈值）。
 * Q2 风险色条错误：高风险红、其他当前风险橙、无风险不显示。
 * Q3 头像情绪圆点缺失或颜色与情绪不符。
 * Q4 第二行标签多于一个，或风险类型与 AI 优先级错误（风险优先）。
 */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import type { ReceptionItem } from '../../api/client'
import { QueueRow, sameQueueRow, waitLabel } from './QueueRow'

const base: ReceptionItem = {
  conversationId: 'c1', buyerAlias: '魏h**', title: 't', preview: '还没到账', updatedAt: '2026-05-07T10:00:00+00:00',
  dataSource: 'live', messageRevision: 1, unreadCount: 0, serviceMode: 'autonomous', modeRevision: 0,
  autoReplyStatus: 'idle', activeRiskTypes: [], reviewRiskTypes: [], waitThresholdSeconds: 120,
}
const now = Date.parse('2026-05-07T10:05:00+00:00')
const row = (patch: Partial<ReceptionItem>) => render(<MemoryRouter>
  <QueueRow item={{ ...base, ...patch }} active={false} now={now} onOpen={() => {}} /></MemoryRouter>)

describe('QueueRow', () => {
  it('Q1 wait label only past threshold', () => {
    expect(waitLabel({ ...base, waitingSince: '2026-05-07T10:04:30+00:00' }, now)).toBeNull()
    expect(waitLabel({ ...base, waitingSince: '2026-05-07T10:02:00+00:00' }, now)).toBe('等待 3 分')
    // 全景方案 5.1：活动窗口（120 分钟）外不再显示“等待 220 小时”
    expect(waitLabel({ ...base, waitingSince: new Date(now - 3 * 3600_000).toISOString() }, now)).toBeNull()
    expect(waitLabel({ ...base, waitingSince: new Date(now - 95 * 60_000).toISOString() }, now)).toBe('等待 1 小时 35 分')
    const { container } = row({ waitingSince: '2026-05-07T10:02:00+00:00' })
    expect(container.querySelector('.yt-queue-wait')?.textContent).toBe('等待 3 分')
  })
  it('Q2 risk strip', () => {
    expect(row({ riskLevel: 'high', activeRiskTypes: ['complaint_risk'] }).container.querySelector('.is-risk-high')).toBeTruthy()
    expect(row({ activeRiskTypes: ['response_wait'] }).container.querySelector('.is-risk-medium')).toBeTruthy()
    const { container } = row({})
    expect(container.querySelector('.is-risk-high, .is-risk-medium')).toBeNull()
  })
  it('Q3 emotion dot', () => {
    expect(row({ currentEmotion: 'angry' }).container.querySelector('.yt-emotion-dot.is-angry')).toBeTruthy()
  })
  it('Q4 one tag, risk first', () => {
    row({ activeRiskTypes: ['complaint_risk', 'response_wait'] })
    expect(screen.getAllByTestId('queue-tag')).toHaveLength(1)
    expect(screen.getByTestId('queue-tag').textContent).not.toBe('AI')
  })
  it('Q4 AI tag when autonomous without risk', () => {
    row({})
    expect(screen.getByTestId('queue-tag').textContent).toBe('AI')
  })
})

/**
 * 队列记忆化（P2-2）。
 * M1 轮询每次返回新对象，内容不变也整列重渲，长队列卡顿；
 * M2 只比引用会漏掉内容变化（新消息、风险标签、未读数）；
 * M3 时钟每 30 秒跳动，等待文案没变也全部重渲。
 */
describe('sameQueueRow', () => {
  const open = () => {}
  const props = (patch: Partial<ReceptionItem> = {}, at = now) => ({ item: { ...base, ...patch }, active: false, now: at, onOpen: open })
  it('内容相同的新对象不重渲', () => { expect(sameQueueRow(props(), props())).toBe(true) })
  it('内容变化必须重渲', () => {
    expect(sameQueueRow(props(), props({ unreadCount: 2 }))).toBe(false)
    expect(sameQueueRow(props(), props({ activeRiskTypes: ['emotion_escalation'] }))).toBe(false)
  })
  it('时钟跳动但等待文案不变时不重渲，文案变化时重渲', () => {
    const start = Date.parse('2026-05-07T10:00:00Z')
    const waiting = { waitingSince: '2026-05-07T10:00:00Z' }
    const at = start + 300_000
    expect(sameQueueRow(props(waiting, at), props(waiting, at + 10_000))).toBe(true)
    expect(sameQueueRow(props(waiting, at), props(waiting, at + 60_000))).toBe(false)
  })
})
