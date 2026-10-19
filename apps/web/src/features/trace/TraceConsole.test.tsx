/**
 * 追踪台失败方式：C1 打不开深链接指定的追踪；C2 编排/引用视图缺失或切换无效；C3 点编排卡片打不开检查器；C4 检查器不显示模型版本与用量；
 * C5（反馈 10-18 #3a）后端模型调用 kind=model_call 时检查器输入/输出显示「无」；卡片没有一句话产出与模型名。
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ traces: vi.fn(), trace: vi.fn(), traceArtifact: vi.fn(), traceExport: vi.fn(), sourceRecord: vi.fn() }))
vi.mock('../../api/client', async (load) => ({ ...(await load<object>()), platformApi: api }))
import { TraceConsole } from './TraceConsole'

const t = (ms: number) => new Date(Date.parse('2026-05-01T00:00:00Z') + ms).toISOString()
const span = (o: Record<string, unknown>) => ({ parentSpanId: null, attempt: 1, parallelGroup: null, status: 'ok', label: '', reasons: [], kind: 'agent', ...o })
const detail = { traceId: 'trc-2', graph: 'reception', triggerType: 'message', status: 'sent', triggerText: '面霜什么时候发货', outcomeText: '亲，已经在打包啦', orchestration: 'multi', startedAt: t(0), endedAt: t(2000),
  totals: {}, lanes: [], versions: {}, citations: [{ replyStyle: 'recommended', segmentIndex: 1, segmentText: '售后在处理', sourceId: 'ticket:K1', sheetName: '售后表', rowNumber: 12, verdict: 'verified' }],
  spans: [span({ spanId: 'a', seq: 0, name: 'composer', summary: '草稿 86 字', inputArtifact: 'in-a', outputArtifact: 'out-a', startedAt: t(0), endedAt: t(1500), durationMs: 1500 }),
    span({ spanId: 'm', seq: 1, kind: 'model_call', inputArtifact: 'in-m', outputArtifact: 'out-m', parentSpanId: 'a', name: 'composer', startedAt: t(100), endedAt: t(1400), durationMs: 1300, modelReturned: 'qwen-plus', promptTokens: 6800, completionTokens: 410, promptCode: 'YT_COMPOSER', promptRevision: 'r3' })] }

beforeEach(() => {
  api.traces.mockResolvedValue({ total: 2, items: [
    { ...detail, traceId: 'trc-1', buyerAlias: '甲', lanes: [{ durationMs: 10 }] }, { ...detail, buyerAlias: '乙', lanes: [{ durationMs: 10 }] }] })
  api.trace.mockResolvedValue(detail)
  api.traceArtifact.mockImplementation(async (sha: string) => ({ sha256: sha, kind: 'x', content: `内容-${sha}` }))
})

describe('TraceConsole', () => {
  it('C1–C4', async () => {
    render(<ConfigProvider><TraceConsole initialTrace="trc-2" /></ConfigProvider>)
    expect(await screen.findByText(/trc-2 · 多 Agent/)).toBeInTheDocument()
    expect(api.trace).toHaveBeenCalledWith('trc-2')
    expect(screen.getByLabelText('编排流程')).toBeInTheDocument()
    expect(screen.getAllByText('草稿 86 字').length).toBeGreaterThan(0)
    expect(screen.getAllByText('qwen-plus').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: '共情起草' }))
    expect(await screen.findByText('内容-in-a')).toBeInTheDocument()
    expect(await screen.findByText('内容-in-m')).toBeInTheDocument()
    // 反馈 10-19 #1：起点是客户原话、终点是发出的回复
    expect(screen.getByText('面霜什么时候发货')).toBeInTheDocument()
    expect(screen.getByText('亲，已经在打包啦')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '问题' })).toBeNull()
    fireEvent.click(await screen.findByRole('tab', { name: '模型' }))
    expect(await screen.findByText('YT_COMPOSER@r3')).toBeInTheDocument()
    expect(screen.getAllByText('qwen-plus').length).toBeGreaterThan(1)
    fireEvent.click(screen.getByText('引用'))
    expect(await screen.findByText('售后表 第 12 行')).toBeInTheDocument()
    expect(screen.queryByText('黑板')).toBeNull()
    expect(screen.queryByText('时序')).toBeNull()
  })
})
