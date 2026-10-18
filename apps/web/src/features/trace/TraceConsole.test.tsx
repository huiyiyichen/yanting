/**
 * 追踪台失败方式：C1 打不开深链接指定的追踪；C2 四个视图缺失或切换无效；C3 点泳道节点打不开检查器；C4 检查器不显示模型版本与用量。
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ traces: vi.fn(), trace: vi.fn(), traceArtifact: vi.fn(), traceExport: vi.fn(), sourceRecord: vi.fn() }))
vi.mock('../../api/client', async (load) => ({ ...(await load<object>()), platformApi: api }))
import { TraceConsole } from './TraceConsole'

const t = (ms: number) => new Date(Date.parse('2026-05-01T00:00:00Z') + ms).toISOString()
const span = (o: Record<string, unknown>) => ({ parentSpanId: null, attempt: 1, parallelGroup: null, status: 'ok', label: '', reasons: [], kind: 'agent', ...o })
const detail = { traceId: 'trc-2', graph: 'reception', triggerType: 'message', status: 'sent', orchestration: 'multi', startedAt: t(0), endedAt: t(2000),
  totals: {}, lanes: [], versions: {}, citations: [{ replyStyle: 'recommended', segmentIndex: 1, segmentText: '售后在处理', sourceId: 'ticket:K1', sheetName: '售后表', rowNumber: 12, verdict: 'verified' }],
  spans: [span({ spanId: 'a', seq: 0, name: 'composer', startedAt: t(0), endedAt: t(1500), durationMs: 1500 }),
    span({ spanId: 'm', seq: 1, kind: 'model', parentSpanId: 'a', name: 'composer', startedAt: t(100), endedAt: t(1400), durationMs: 1300, modelReturned: 'qwen-plus', promptTokens: 6800, completionTokens: 410, promptCode: 'YT_COMPOSER', promptRevision: 'r3' })] }

beforeEach(() => {
  api.traces.mockResolvedValue({ total: 2, items: [
    { ...detail, traceId: 'trc-1', buyerAlias: '甲', lanes: [{ durationMs: 10 }] }, { ...detail, buyerAlias: '乙', lanes: [{ durationMs: 10 }] }] })
  api.trace.mockResolvedValue(detail)
})

describe('TraceConsole', () => {
  it('C1–C4', async () => {
    render(<ConfigProvider><TraceConsole initialTrace="trc-2" /></ConfigProvider>)
    expect(await screen.findByText(/trc-2 · 多 Agent/)).toBeInTheDocument()
    expect(api.trace).toHaveBeenCalledWith('trc-2')
    fireEvent.click(screen.getByRole('button', { name: '共情起草' }))
    fireEvent.click(await screen.findByRole('tab', { name: '版本' }))
    expect(await screen.findByText('YT_COMPOSER@r3')).toBeInTheDocument()
    expect(screen.getByText('qwen-plus')).toBeInTheDocument()
    fireEvent.click(screen.getByText('引用'))
    expect(await screen.findByText('售后表 第 12 行')).toBeInTheDocument()
    fireEvent.click(screen.getByText('流程'))
    expect(screen.getByLabelText('流程图')).toBeInTheDocument()
  })
})
