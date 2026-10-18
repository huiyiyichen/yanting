/**
 * 全景页面（全景方案 3.3–3.5）失败方式：
 * P1 色块不在其泳道内（待人工的会话出现在 AI 接待中）。
 * P2 筛选把不符合的色块隐藏或跳位（应淡化保留）。
 * P3 接管不走服务模式接口；人工处理中仍显示“接管”。
 * P4 “打开会话”不回到工作台并选中会话。
 * P5 暂停刷新后仍在请求。
 * P6 待人工的预览缺少转人工原因与原话；步骤缺失。
 * P7 上一轮不按 Agent 列出：并行组不缩进、没有逐项耗时、没有跳到模型配置页「Agent 追踪」的入口（多 Agent 8.2）。
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PanoramaItem } from '../../api/client'

const api = vi.hoisted(() => ({ panorama: vi.fn(), receptionMessages: vi.fn(), setReceptionMode: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<object>()), supportApi: api }))
import { MemoryRouter } from 'react-router-dom'
import { Panorama } from './Panorama'

const at = new Date().toISOString()
const item = (id: string, patch: Partial<PanoramaItem>): PanoramaItem => ({
  conversationId: id, buyerAlias: id, scene: '物流咨询', lane: 'ai', emotionBands: ['calm'], highRisk: false,
  lastActivityAt: at, laneEnteredAt: at, ...patch,
} as PanoramaItem)
const steps = ['安全检查', '读取轨迹', '知识检索', '起草', '核验', '发送'].map((name, i) => ({ name, status: i === 0 ? 'fail' : 'pending', durationMs: i ? 0 : 20, attempts: 1 }))

beforeEach(() => {
  vi.clearAllMocks()
  api.panorama.mockResolvedValue({ running: 1, queued: 0, activeWindowMinutes: 120, items: [
    item('甲', { aiJob: 'running', currentRun: { steps: steps.map((s) => ({ ...s, status: s.name === '起草' ? 'active' : 'pending' })) } }),
    item('乙', { lane: 'wait', highRisk: true, emotionBands: ['dissatisfied', 'angry'], waitingSince: at,
      handoffReason: '投诉风险', handoffQuote: '不然我直接投诉到平台', lastRun: { outcome: 'handoff', traceId: 'trc-1', steps: [
      { name: '安全闸门', status: 'done', durationMs: 5, attempts: 1 }, { name: '轨迹查询', status: 'done', durationMs: 300, group: 'fanout', attempts: 1 },
      { name: '知识', status: 'done', durationMs: 800, group: 'fanout', attempts: 1 }, { name: '共情起草', status: 'fail', durationMs: 1200, attempts: 2 }] } }),
    item('丙', { lane: 'human', handler: '客服' }),
  ] })
  api.receptionMessages.mockResolvedValue([])
  api.setReceptionMode.mockResolvedValue({})
})

const mount = (onOpen = vi.fn()) => { render(<MemoryRouter><ConfigProvider><Panorama onOpen={onOpen} /></ConfigProvider></MemoryRouter>); return onOpen }

describe('Panorama', () => {
  it('P1/P2 泳道归属与筛选淡化', async () => {
    mount()
    const wait = await screen.findByRole('region', { name: '待人工' })
    expect(within(wait).getByRole('button', { name: /^乙，待人工，不满、激烈，高风险/ })).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'AI 接待中' })).getByRole('button', { name: /^甲/ })).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: '人工处理中' })).getByRole('button', { name: /^丙/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('radio', { name: /有风险 1/ }))
    expect(screen.getByRole('button', { name: /^甲/ })).toHaveClass('is-dim')
    expect(screen.getByRole('button', { name: /^乙/ })).not.toHaveClass('is-dim')
  })
  it('P3/P4/P6 预览：原因、步骤、接管与打开会话', async () => {
    const onOpen = mount()
    fireEvent.click(await screen.findByRole('button', { name: /^乙/ }))
    const reason = screen.getByRole('region', { name: '转人工原因' })
    expect(reason).toHaveTextContent('投诉风险')
    expect(reason).toHaveTextContent('不然我直接投诉到平台')
    const last = screen.getByRole('region', { name: '上一轮 AI 处理' })
    expect(last).toHaveTextContent('转人工')
    const rows = within(last).getAllByRole('listitem')
    expect(rows.map((row) => row.className.includes('is-par'))).toEqual([false, true, true, false])
    expect(rows[2]).toHaveTextContent('0.8s')
    expect(rows[3]).toHaveTextContent('×2')
    expect(within(last).getByRole('link', { name: '查看追踪' })).toHaveAttribute('href', '/platform/models?tab=trace&trace=trc-1')
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /接\s?管/ })) })
    expect(api.setReceptionMode).toHaveBeenCalledWith('乙', 'operator_assisted')
    fireEvent.click(screen.getByRole('button', { name: '打开会话' }))
    expect(onOpen).toHaveBeenCalledWith('乙')
    fireEvent.click(screen.getByRole('button', { name: /^丙/ }))
    expect(screen.queryByRole('button', { name: /接\s?管/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /^甲/ }))
    expect(screen.getByRole('region', { name: 'AI 处理中' })).toBeInTheDocument()
  })
  it('P5 暂停后不再请求', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    mount()
    await act(async () => { await Promise.resolve() })
    fireEvent.click(screen.getByRole('button', { name: '实时' }))
    const calls = api.panorama.mock.calls.length
    await act(async () => { vi.advanceTimersByTime(5000) })
    expect(api.panorama.mock.calls.length).toBe(calls)
    vi.useRealTimers()
  })
})
