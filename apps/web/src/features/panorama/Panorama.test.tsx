/**
 * 全景页面（全景方案 3.3–3.5）失败方式：
 * P1 色块不在其泳道内（待人工的会话出现在 AI 接待中）。
 * P2 筛选把不符合的色块隐藏或跳位（应淡化保留）。
 * P3 接管不走服务模式接口；人工处理中仍显示“接管”。
 * P4 “打开会话”不回到工作台并选中会话。
 * P5 暂停刷新后仍在请求。
 * P6 待人工的预览缺少转人工原因与原话；步骤缺失。
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PanoramaItem } from '../../api/client'

const api = vi.hoisted(() => ({ panorama: vi.fn(), receptionMessages: vi.fn(), setReceptionMode: vi.fn() }))
vi.mock('../../api/client', async (orig) => ({ ...(await orig<object>()), supportApi: api }))
import { Panorama } from './Panorama'

const at = new Date().toISOString()
const item = (id: string, patch: Partial<PanoramaItem>): PanoramaItem => ({
  conversationId: id, buyerAlias: id, scene: '物流咨询', lane: 'ai', emotionBands: ['calm'], highRisk: false,
  lastActivityAt: at, laneEnteredAt: at, ...patch,
} as PanoramaItem)
const steps = ['安全检查', '读取轨迹', '知识检索', '起草', '核验', '发送'].map((name, i) => ({ name, status: i === 0 ? 'fail' : 'pending', durationMs: i ? 0 : 20 }))

beforeEach(() => {
  vi.clearAllMocks()
  api.panorama.mockResolvedValue({ running: 1, queued: 0, activeWindowMinutes: 120, items: [
    item('甲', { aiJob: 'running', currentRun: { steps: steps.map((s) => ({ ...s, status: s.name === '起草' ? 'active' : 'pending' })) } }),
    item('乙', { lane: 'wait', highRisk: true, emotionBands: ['dissatisfied', 'angry'], waitingSince: at,
      handoffReason: '投诉风险', handoffQuote: '不然我直接投诉到平台', lastRun: { outcome: 'handoff', steps } }),
    item('丙', { lane: 'human', handler: '客服' }),
  ] })
  api.receptionMessages.mockResolvedValue([])
  api.setReceptionMode.mockResolvedValue({})
})

const mount = (onOpen = vi.fn()) => { render(<ConfigProvider><Panorama onOpen={onOpen} /></ConfigProvider>); return onOpen }

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
    expect(screen.getByRole('region', { name: '上一轮 AI 处理' })).toHaveTextContent('转人工')
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
