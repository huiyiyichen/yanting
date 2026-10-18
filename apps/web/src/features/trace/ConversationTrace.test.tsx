/**
 * 接待插件「轨迹」页签（反馈 10-18 #3）失败方式：
 * P1 没有默认展示最新一轮；P2 切换轮次不重新加载；P3 点卡片打不开检查器；P4 没有记录时空白无提示。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ traces: vi.fn(), trace: vi.fn(), traceArtifact: vi.fn() }))
vi.mock('../../api/client', async (load) => ({ ...(await load<object>()), platformApi: api }))
import { ConversationTrace } from './ConversationTrace'

const t = (ms: number) => new Date(Date.parse('2026-10-18T02:00:00Z') + ms).toISOString()
const span = (o: Record<string, unknown>) => ({ parentSpanId: null, attempt: 1, parallelGroup: null, status: 'ok', label: '', reasons: [], kind: 'agent', startedAt: t(0), endedAt: t(100), durationMs: 100, ...o })
const detail = (id: string, summary: string) => ({ traceId: id, status: 'sent', orchestration: 'multi', startedAt: t(0), endedAt: t(900), citations: [], totals: {}, lanes: [], versions: {},
  spans: [span({ spanId: `${id}-k`, seq: 0, name: 'knowledge', summary }), span({ spanId: `${id}-c`, seq: 1, name: 'composer', summary: '草稿 52 字' })] })

beforeEach(() => {
  api.traces.mockResolvedValue({ total: 2, items: [{ traceId: 'new', status: 'sent', startedAt: t(60000), lanes: [] }, { traceId: 'old', status: 'failed', startedAt: t(0), lanes: [] }] })
  api.trace.mockImplementation(async (id: string) => detail(id, id === 'new' ? '命中 2 条知识：洁面' : '未命中相关知识'))
  api.traceArtifact.mockResolvedValue({ sha256: 'x', kind: 'x', content: '' })
})

describe('ConversationTrace', () => {
  it('P1–P3', async () => {
    render(<ConfigProvider><MemoryRouter><ConversationTrace conversationId="c1" /></MemoryRouter></ConfigProvider>)
    expect(await screen.findByText('命中 2 条知识：洁面')).toBeInTheDocument()
    expect(api.traces).toHaveBeenCalledWith({ conversationId: 'c1', limit: 12 })
    expect(screen.getByText(/第 2 轮 .*（最新）/)).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '切换轮次' }))
    fireEvent.click(await screen.findByText(/第 1 轮/))
    expect(await screen.findByText('未命中相关知识')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '共情起草' }))
    await waitFor(() => expect(screen.getAllByText('草稿 52 字').length).toBeGreaterThan(1))
  })
  it('P4', async () => {
    api.traces.mockResolvedValue({ total: 0, items: [] })
    render(<ConfigProvider><MemoryRouter><ConversationTrace conversationId="c1" /></MemoryRouter></ConfigProvider>)
    expect(await screen.findByText('这段对话还没有 AI 编排记录')).toBeInTheDocument()
  })
})
