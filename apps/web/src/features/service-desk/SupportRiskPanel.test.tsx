import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RiskIncidentView } from '../../api/client'
import { SupportRiskPanel } from './SupportRiskPanel'

const api = vi.hoisted(() => ({ read: vi.fn(), intervene: vi.fn() }))
vi.mock('../../api/client', async (original) => {
  const actual = await original<typeof import('../../api/client')>()
  return { ...actual, deskApi: { ...actual.deskApi, conversationRisks: api.read, interveneRisk: api.intervene } }
})

const incident: RiskIncidentView = {
  incidentId: 'incident-1', buyerAlias: '消费者甲', conversationIds: ['c1'], orderIds: [],
  workOrderIds: [], riskLevel: 'medium', riskStatus: 'pending', latestMessage: '请查物流',
  updatedAt: '2026-10-03T01:00:00Z', recommendedAction: '优先回应消费者',
  openTicketCount: 0, needsReview: false, version: 'v1', triageScore: 51, historicalSensitivity: 0,
  recurrenceCount: 0, signalActive: true,
  triageLabel: 'priority', attentionState: 'active', currentEmotion: 'calm',
  serviceState: 'live', currentAction: 'intervene', emotionTrend: 'stable',
  signals: [{
    alertId: 'a1', conversationId: 'c1', buyerAlias: '消费者甲', riskType: 'response_wait',
    riskLevel: 'medium', riskStatus: 'pending', signalActive: true,
    triggerSummary: '消费者超过120秒未获回复', recommendedAction: '优先回应消费者',
    evidenceRefs: ['m1'], createdAt: '2026-10-03T01:00:00Z', updatedAt: '2026-10-03T01:02:00Z',
    episode: 1, revision: 1, ruleVersion: 'explicit-fixture',
    conditions: { demoRule: true, waitingSince: '2026-10-03T01:00:00Z' },
  }],
}
function mount(conversationId = 'c1', enabled = true) {
  return render(<ConfigProvider><MemoryRouter>
    <SupportRiskPanel conversationId={conversationId} enabled={enabled} refreshKey="1" />
  </MemoryRouter></ConfigProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  api.read.mockResolvedValue([incident])
  api.intervene.mockResolvedValue({ incident, contexts: [], evidence: [], tickets: [], handlingHistory: [] })
})

describe('客服当前风险建议', () => {
  it('无AI建议也展示最新原因与动作，只显示未关闭风险', async () => {
    api.read.mockResolvedValue([incident, { ...incident, incidentId: 'closed', riskStatus: 'resolved',
      signals: [{ ...incident.signals[0], riskStatus: 'resolved', triggerSummary: '已关闭的旧原因' }] }])
    mount()
    expect(await screen.findByText('消费者超过120秒未获回复')).toBeInTheDocument()
    expect(screen.getByText('优先回应消费者')).toBeInTheDocument()
    expect(screen.getByText('中风险')).toBeInTheDocument()
    expect(screen.queryByText('Demo规则')).not.toBeInTheDocument()
    expect(screen.queryByText(/等待起点/)).not.toBeInTheDocument()
    expect(screen.queryByText('已关闭的旧原因')).not.toBeInTheDocument()
    expect(api.read).toHaveBeenCalledWith('c1')
    expect(screen.getByRole('link', { name: '查看未回复预警处置详情' })).toHaveAttribute(
      'href', '/risk?incident=incident-1&conversation=c1&type=response_wait',
    )
  })

  it('失焦返回时更新复核/关闭结果，不再提示旧介入动作', async () => {
    mount()
    await screen.findByText('优先回应消费者')
    api.read.mockResolvedValue([{ ...incident, attentionState: 'review',
      signals: [{ ...incident.signals[0], signalActive: false }] }])
    await act(async () => { window.dispatchEvent(new Event('focus')) })
    expect(await screen.findByText('核对最新反馈与处理结果，确认后关闭')).toBeInTheDocument()
    expect(screen.queryByText('优先回应消费者')).not.toBeInTheDocument()
    api.read.mockResolvedValue([{ ...incident, riskStatus: 'resolved', attentionState: 'closed' }])
    await act(async () => { window.dispatchEvent(new Event('focus')) })
    expect(await screen.findByText('暂无待处理风险')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '查看未回复预警处置详情' })).not.toBeInTheDocument()
  })

  it('临期事项保留各个工单期限与直接查看入口', async () => {
    api.read.mockResolvedValue([{ ...incident, signals: [{
      ...incident.signals[0], riskType: 'followup_due_soon',
      conditions: { deadlines: [
        { ticketId: 'T001', dueAt: '2026-10-03T01:20:00Z' },
        { ticketId: 'T002', dueAt: '2026-10-03T01:25:00Z' },
      ] },
    }] }])
    mount()
    expect(await screen.findByRole('link', { name: 'T001' })).toHaveAttribute(
      'href', '/platform/work-orders?ticket=T001',
    )
    expect(screen.getByRole('link', { name: 'T002' })).toHaveAttribute(
      'href', '/platform/work-orders?ticket=T002',
    )
  })

  it('切换会话后忽略旧请求，隐藏插件不进行读取', async () => {
    let resolve!: (rows: RiskIncidentView[]) => void
    api.read.mockReturnValueOnce(new Promise<RiskIncidentView[]>((done) => { resolve = done }))
    const { rerender } = mount()
    await waitFor(() => expect(api.read).toHaveBeenCalledWith('c1'))
    api.read.mockResolvedValue([])
    rerender(<ConfigProvider><MemoryRouter>
      <SupportRiskPanel conversationId="c2" enabled refreshKey="1" />
    </MemoryRouter></ConfigProvider>)
    await screen.findByText('暂无待处理风险')
    await act(async () => { resolve([incident]) })
    expect(screen.queryByText('消费者超过120秒未获回复')).not.toBeInTheDocument()
    rerender(<ConfigProvider><MemoryRouter>
      <SupportRiskPanel conversationId="c3" enabled={false} refreshKey="1" />
    </MemoryRouter></ConfigProvider>)
    expect(api.read).not.toHaveBeenCalledWith('c3')
  })

  it('风险读取失败明确显示错误并可重试', async () => {
    const user = userEvent.setup()
    api.read.mockRejectedValueOnce(new Error('连接中断'))
    mount()
    expect(await screen.findByText('风险读取失败：连接中断')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '刷新风险关注' }))
    expect(await screen.findByText('优先回应消费者')).toBeInTheDocument()
    expect(screen.queryByText('风险读取失败：连接中断')).not.toBeInTheDocument()
  })

  it('刷新失败时保留上一次已读到的风险内容', async () => {
    const user = userEvent.setup()
    mount()
    expect(await screen.findByText('消费者超过120秒未获回复')).toBeInTheDocument()
    api.read.mockRejectedValueOnce(new Error('暂时不可用'))
    await user.click(screen.getByRole('button', { name: '刷新风险关注' }))
    expect(await screen.findByText('风险读取失败：暂时不可用')).toBeInTheDocument()
    expect(screen.getByText('消费者超过120秒未获回复')).toBeInTheDocument()
  })

  it('人工接待状态下不重复显示接管按钮', async () => {
    render(<ConfigProvider><MemoryRouter>
      <SupportRiskPanel conversationId="c1" enabled refreshKey="1" serviceMode="operator_assisted" />
    </MemoryRouter></ConfigProvider>)
    await screen.findByText('消费者超过120秒未获回复')
    expect(screen.queryByRole('button', { name: /接管会话/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '开始处理' })).toBeInTheDocument()
    expect(screen.getByText('待介入')).toBeInTheDocument()
  })

  it('当前风险可直接接管会话，不打开额外处置表单', async () => {
    const user = userEvent.setup()
    const processed = { ...incident, riskStatus: 'in_progress' as const, version: 'v2',
      signals: [{ ...incident.signals[0], riskStatus: 'in_progress' as const }] }
    api.intervene.mockImplementation(async () => {
      api.read.mockResolvedValue([processed])
      return { incident: processed, contexts: [], evidence: [], tickets: [], handlingHistory: [] }
    })
    const onIntervened = vi.fn().mockResolvedValue(undefined)
    render(<ConfigProvider><MemoryRouter>
      <SupportRiskPanel conversationId="c1" enabled refreshKey="1" serviceMode="operator_assisted"
        onIntervened={onIntervened} />
    </MemoryRouter></ConfigProvider>)
    await user.click(await screen.findByRole('button', { name: '开始处理' }))
    expect(api.intervene).toHaveBeenCalledWith('incident-1', 'c1', 'v1')
    expect(await screen.findByText('处理中')).toBeInTheDocument()
    expect(await screen.findByText('继续回复消费者当前问题')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /接管会话/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '开始处理' })).not.toBeInTheDocument()
    expect(onIntervened).toHaveBeenCalledWith('c1')
  })

  it('人工接待不改变待复核风险的状态', async () => {
    api.read.mockResolvedValue([{
      ...incident, currentAction: 'review', attentionState: 'review', signalActive: false,
      signals: [{ ...incident.signals[0], signalActive: false }],
    }])
    render(<ConfigProvider><MemoryRouter>
      <SupportRiskPanel conversationId="c1" enabled refreshKey="1" serviceMode="operator_assisted" />
    </MemoryRouter></ConfigProvider>)
    expect(await screen.findByText('待复核')).toBeInTheDocument()
    expect(screen.queryByText('处理中')).not.toBeInTheDocument()
  })

  it('客户主动转人工不等于风险已介入', async () => {
    api.read.mockResolvedValue([incident])
    render(<ConfigProvider><MemoryRouter>
      <SupportRiskPanel conversationId="c1" enabled refreshKey="1" serviceMode="operator_assisted" />
    </MemoryRouter></ConfigProvider>)
    expect(await screen.findByText('待介入')).toBeInTheDocument()
    expect(screen.queryByText('处理中')).not.toBeInTheDocument()
  })

  it('不把关联订单其他会话的未回复提醒堆到当前会话', async () => {
    api.read.mockResolvedValue([{ ...incident, conversationIds: ['c1', 'c2', 'c3'], signals: [
      incident.signals[0],
      { ...incident.signals[0], alertId: 'other-2', conversationId: 'c2', triggerSummary: '其他会话等待' },
      { ...incident.signals[0], alertId: 'duplicate', triggerSummary: '本轮最新等待',
        updatedAt: '2026-10-03T01:03:00Z' },
    ] }])
    mount()
    expect(await screen.findByText('本轮最新等待')).toBeInTheDocument()
    expect(screen.getAllByText('未回复预警')).toHaveLength(1)
    expect(screen.queryByText('其他会话等待')).not.toBeInTheDocument()
    expect(screen.queryByText('消费者超过120秒未获回复')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: '接管会话' })).toHaveLength(1)
  })

  it('跟进期限提醒不因风险处理中变成泛泛的回复指令', async () => {
    api.read.mockResolvedValue([{ ...incident, riskStatus: 'in_progress', signals: [{
      ...incident.signals[0], riskType: 'followup_due_soon', riskStatus: 'in_progress',
      recommendedAction: '联系物流负责人核对处理进度',
    }] }])
    mount()
    expect(await screen.findByText('联系物流负责人核对处理进度')).toBeInTheDocument()
    expect(screen.queryByText('继续回复消费者当前问题')).not.toBeInTheDocument()
  })
})
