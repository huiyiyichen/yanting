import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RiskDashboardPage } from './RiskDashboardPage'
import { ApiError } from '../api/client'
import { emotionStatus } from '../features/service-desk/riskPresentation'

const api = vi.hoisted(() => ({
  risks: vi.fn(), reception: vi.fn(), risk: vi.fn(), analyze: vi.fn(), operators: vi.fn(), intervene: vi.fn(), judge: vi.fn(),
}))

vi.mock('../api/client', async (original) => {
  const actual = await original<typeof import('../api/client')>()
  return {
    ...actual,
    deskApi: { ...actual.deskApi, risks: api.risks, risk: api.risk, analyzeBreakpoints: api.analyze, operators: api.operators,
      interveneRisk: api.intervene, judgeRisk: api.judge },
    supportApi: { ...actual.supportApi, reception: api.reception },
  }
})

const incident = {
  incidentId: 'incident-1', buyerAlias: '消费者甲', conversationIds: ['conv-1'], primaryConversationId: 'conv-1', orderIds: [],
  workOrderIds: [], riskLevel: 'medium', riskStatus: 'pending', latestMessage: '物流仍未更新',
  updatedAt: '2026-10-02T08:00:00Z', recommendedAction: '核对实际进展',
  openTicketCount: 0, needsReview: true, signalActive: true, version: 'version-1',
  triageScore: 58, triageLabel: 'priority', triageReasons: ['服务断点', '待人工复核'], historicalSensitivity: 0, attentionState: 'active',
  currentEmotion: 'dissatisfied', emotionTrend: 'rising', serviceState: 'live', currentAction: 'intervene',
  signals: [{ alertId: 'signal-1', riskType: 'service_breakpoint', riskStatus: 'pending',
    conversationId: 'conv-1', evidenceRefs: [], riskLevel: 'medium', signalActive: true,
    triggerSummary: '同一诉求反复提出', recommendedAction: '核对实际进展' }],
}
const assessment = {
  conversationId: 'conv-1', assessmentId: 'analysis-1', analyzed: true, stale: true,
  revision: 1, modelId: 'explicit-fixture', updatedAt: '2026-10-02T08:00:00Z',
  findings: [{
    kind: 'repeated_question', kindLabel: '重复咨询未解决', topic: '物流进度',
    reason: '消费者连续追问物流，需核实实际进展', detectedAt: '2026-10-02T08:00:00Z',
    recommendedAction: '核对历史答复和实际进展',
    evidence: [
      { sourceRef: 'm1', quote: '请问物流有没有进展', kind: 'customer_message', label: '消费者自述', occurredAt: '2026-10-02T07:00:00Z' },
      { sourceRef: 'm2', quote: '物流仍未更新', kind: 'customer_message', label: '消费者自述', occurredAt: '2026-10-02T08:00:00Z' },
    ],
  }],
}

let detail: object
beforeEach(() => {
  vi.clearAllMocks()
  detail = { incident, contexts: [], evidence: [], tickets: [], handlingHistory: [],
    serviceBreakpointAssessments: [assessment] }
  api.risks.mockResolvedValue([incident])
  api.reception.mockResolvedValue({ items: [], unreadTotal: 0 })
  api.risk.mockImplementation(async () => detail)
  api.analyze.mockResolvedValue({ ...assessment, stale: false })
  api.intervene.mockImplementation(async () => detail)
  api.judge.mockImplementation(async () => detail)
  api.operators.mockResolvedValue({ defaultOperatorId: 'G001', operators: [{ operatorId: 'G001', name: '模拟客服 G001' }] })
})

function renderPage(path = '/risk') {
  return render(<ConfigProvider><MemoryRouter initialEntries={[path]}><RiskDashboardPage /><Location /></MemoryRouter></ConfigProvider>)
}

function Location() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

async function openBreakpoints(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId('risk-open-incident-1'))
  await user.click(await screen.findByText('服务排查'))
  await screen.findByRole('heading', { name: '物流进度 · 重复咨询未解决' })
}

describe('风险服务断点', () => {
  it('首次打开前置官方历史记录并能打开对应会话', async () => {
    const user = userEvent.setup()
    const official = {
      ...incident, incidentId: 'official-146', buyerAlias: '雷**',
      conversationIds: ['S00146'], primaryConversationId: 'S00146',
      currentAction: 'record_only', serviceState: 'historical',
      signals: [{ ...incident.signals[0], conversationId: 'S00146', currentAttention: 'historical' }],
    }
    api.risks.mockResolvedValue([incident, official])
    renderPage()
    expect(await screen.findByTestId('risk-open-official-146')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '官方记录 1' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByTestId('risk-open-incident-1')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '打开会话 雷**' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/support?conversation=S00146')
  })

  it('查看证据不调用模型，并保留资料更新后的待分析状态', async () => {
    const user = userEvent.setup()
    renderPage()
    await openBreakpoints(user)
    expect(screen.getAllByText('中风险').length).toBeGreaterThan(0)
    expect(screen.getByText('待更新分析')).toBeInTheDocument()
    expect(screen.getByText('请问物流有没有进展')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '分析服务断点' })).toBeEnabled()
    expect(api.analyze).not.toHaveBeenCalled()
  }, 15000)

  it('明确分析后回读对应会话结果，不发送客服消息', async () => {
    const user = userEvent.setup()
    api.analyze.mockImplementation(async () => {
      detail = { incident, contexts: [], evidence: [], tickets: [], handlingHistory: [],
        serviceBreakpointAssessments: [{ ...assessment, stale: false }] }
      return { ...assessment, stale: false }
    })
    renderPage()
    await openBreakpoints(user)
    await user.click(screen.getByRole('button', { name: '分析服务断点' }))
    await waitFor(() => expect(api.analyze).toHaveBeenCalledTimes(1))
    expect(api.analyze).toHaveBeenCalledWith('conv-1')
    expect(await screen.findByText('已分析')).toBeInTheDocument()
    expect(screen.queryByText('待更新分析')).not.toBeInTheDocument()
  }, 15000)

  it('合并事件只显示一个排查入口，可选择对应会话而不是堆多个检查面板', async () => {
    const user = userEvent.setup()
    const second = { ...assessment, conversationId: 'conv-2', analyzed: false, stale: false, findings: [] }
    detail = { ...detail, serviceBreakpointAssessments: [assessment, second] }
    api.risk.mockResolvedValue(detail)
    renderPage()
    await user.click(await screen.findByTestId('risk-open-incident-1'))
    expect(screen.getAllByText('服务排查')).toHaveLength(1)
    await user.click(await screen.findByText('服务排查'))
    await user.click(screen.getByRole('combobox', { name: '排查会话' }))
    await user.click(await screen.findByText('conv-2', { selector: '.ant-select-item-option-content' }))
    expect(screen.getByRole('button', { name: '分析服务断点 conv-2' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '打开会话 conv-2' })).toBeInTheDocument()
  }, 15000)

  it('分析失败保留旧证据，不显示成功结果', async () => {
    const user = userEvent.setup()
    api.analyze.mockRejectedValueOnce(new Error('模型不可用'))
    renderPage()
    await openBreakpoints(user)
    await user.click(screen.getByRole('button', { name: '分析服务断点' }))
    expect(await screen.findByText('模型不可用')).toBeInTheDocument()
    expect(screen.getByText('待更新分析')).toBeInTheDocument()
    expect(screen.getByText('请问物流有没有进展')).toBeInTheDocument()
    expect(screen.queryByText('分析已保存')).not.toBeInTheDocument()
  }, 15000)

  it('触发条件消退时显示待人工复核，不要求先介入', async () => {
    const user = userEvent.setup()
    const reviewIncident = {
      ...incident, riskStatus: 'pending', signalActive: false, needsReview: true,
      attentionState: 'review', triageLabel: 'review', triageScore: 38,
      currentAction: 'review',
      triageReasons: ['触发条件已消退', '待人工复核'],
      signals: [{ ...incident.signals[0], signalActive: false, conditions: { clearReason: 'consumer_calm_follow_up' } }],
    }
    api.risks.mockResolvedValue([reviewIncident])
    api.risk.mockResolvedValue({ ...detail, incident: reviewIncident })
    renderPage()
    await user.click(await screen.findByRole('tab', { name: /待复核/ }))
    await user.click(await screen.findByTestId('risk-open-incident-1'))
    expect(screen.queryByRole('button', { name: '接管并回复' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /复核关闭/ })).toBeEnabled()
  }, 15000)

  it('客服深链接打开待复核事件后可关闭详情，不会自动弹回', async () => {
    const user = userEvent.setup()
    const record = { ...incident, attentionState: 'review', signalActive: false, currentAction: 'review',
      signals: [{ ...incident.signals[0], signalActive: false }] }
    api.risks.mockResolvedValue([record])
    api.risk.mockResolvedValue({ ...detail, incident: record })
    renderPage('/risk?conversation=conv-1&type=service_breakpoint')
    await waitFor(() => expect(api.risk).toHaveBeenCalledWith('incident-1'))
    expect(await screen.findByRole('button', { name: /复核关闭/ })).toBeEnabled()
    expect(screen.getByRole('tab', { name: /待复核/ })).toHaveAttribute('aria-selected', 'true')
    const openedRequests = api.risk.mock.calls.length
    await user.click(screen.getByRole('button', { name: 'Close' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: /复核关闭/ })).not.toBeInTheDocument())
    expect(api.risk).toHaveBeenCalledTimes(openedRequests)
  }, 15000)

  it('通过明确关联订单跳转时按事件编号打开，不要求来源会话相同', async () => {
    renderPage('/risk?incident=incident-1&conversation=new-conversation&type=service_breakpoint')
    await waitFor(() => expect(api.risk).toHaveBeenCalledWith('incident-1'))
    expect((await screen.findAllByText('中风险')).length).toBeGreaterThan(0)
  }, 15000)

  it('已关闭信号只显示历史状态，不提示当前触发或待关闭', async () => {
    const user = userEvent.setup()
    const record = { ...incident, riskStatus: 'resolved', attentionState: 'closed',
      signalActive: false, needsReview: false, triageScore: 0, serviceState: 'closed', currentAction: 'none',
      signals: [{ ...incident.signals[0], riskStatus: 'resolved', signalActive: true }] }
    api.risks.mockResolvedValue([record])
    api.risk.mockResolvedValue({ ...detail, incident: record })
    renderPage()
    await user.click(await screen.findByRole('tab', { name: '已关闭' }))
    await user.click(await screen.findByTestId('risk-open-incident-1'))
    expect((await screen.findAllByText('已关闭')).length).toBeGreaterThan(1)
    expect(screen.queryByText('当前仍在触发')).not.toBeInTheDocument()
    expect(screen.queryByText('确认风险已消退后复核关闭')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '更多处置' }))
    expect(await screen.findByRole('menuitem', { name: /重新介入/ })).not.toHaveAttribute('aria-disabled', 'true')
  }, 15000)

  it('未回复预警只展示实际原消息和会话入口，不铺规则参数', async () => {
    const user = userEvent.setup()
    const record = {
      ...incident, needsReview: false,
      signals: [{ ...incident.signals[0], riskType: 'response_wait', evidenceRefs: ['m-waiting'],
        triggerSummary: '本次消费者等待已超过120秒，尚无可见服务回复',
        conditions: { basis: 'local_response_wait', demoRule: true, waitThresholdSeconds: 120,
          waitingSince: '2026-10-03T01:00:00Z' } }],
    }
    api.risks.mockResolvedValue([record])
    api.risk.mockResolvedValue({ ...detail, incident: record, evidence: [
      { ref: 'm-waiting', kind: 'message', label: 'conv-1', body: '请核对物流',
        occurredAt: '2026-10-03T01:00:00Z' },
    ] })
    renderPage()
    await user.click(await screen.findByTestId('risk-open-incident-1'))
    await screen.findByRole('heading', { name: '消费者甲' })
    expect(screen.queryByText('等待阈值 120 秒')).not.toBeInTheDocument()
    expect(screen.queryByText('Demo规则')).not.toBeInTheDocument()
    expect(screen.queryByText('依据 本地未回复时长')).not.toBeInTheDocument()
    expect(screen.getAllByText('请核对物流').length).toBeGreaterThan(0)
    expect(api.analyze).not.toHaveBeenCalled()
  }, 15000)

  it('历史服务展示缓和原文和情绪变化，不显示当前介入', async () => {
    const record = {
      ...incident, currentAction: 'record_only', serviceState: 'historical',
      currentEmotion: 'calm', emotionTrend: 'falling', triageScore: 0,
      signals: [{ ...incident.signals[0], currentAttention: 'historical' }],
    }
    api.risks.mockResolvedValue([record])
    api.risk.mockResolvedValue({
      ...detail, incident: record, emotionHistory: [
        { messageId: 'm1', conversationId: 'conv-1', occurredAt: '2026-05-11T02:18:00Z',
          body: '查不出来我就去平台举报', emotion: 'angry' },
        { messageId: 'm2', conversationId: 'conv-1', occurredAt: '2026-05-11T02:25:00Z',
          body: '嗯，这还差不多', emotion: 'calm' },
      ],
    })
    const user = userEvent.setup()
    renderPage('/risk?conversation=conv-1')
    await waitFor(() => expect(api.risk).toHaveBeenCalledWith('incident-1'))
    await screen.findByRole('heading', { name: '消费者甲' })
    await user.click(await screen.findByRole('tab', { name: '服务轨迹' }))
    expect((await screen.findAllByText('嗯，这还差不多')).length).toBeGreaterThan(0)
    expect(screen.getByText('查不出来我就去平台举报')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: '情绪弧线' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '情绪从激烈到平稳' })).toBeInTheDocument()
    expect(screen.getAllByText('平稳 · 缓和').length).toBeGreaterThan(0)
    expect(screen.getByRole('tab', { name: /官方记录 1/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByRole('button', { name: '接管并回复' })).not.toBeInTheDocument()
    expect(api.analyze).not.toHaveBeenCalled()
  }, 15000)

  it('服务结束的临期事项进入工单，不要求重新接管已结束聊天', async () => {
    const user = userEvent.setup()
    const record = {
      ...incident, serviceState: 'closed', currentAction: 'intervene',
      signals: [{ ...incident.signals[0], riskType: 'followup_due_soon', currentAttention: 'active' }],
    }
    api.risks.mockResolvedValue([record])
    api.risk.mockResolvedValue({ ...detail, incident: record, tickets: [{
      ticketId: 't-1', title: '物流跟进', status: 'in_progress',
    }] })
    renderPage()
    await user.click(await screen.findByTestId('risk-open-incident-1'))
    expect(screen.queryByRole('button', { name: '接管并回复' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '跟进工单' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/platform/work-orders?ticket=t-1')
  }, 15000)

  it('重复信号合并标签，持续激烈不写稳定，列表等级和筛选对应', async () => {
    const record = { ...incident, currentEmotion: 'angry', emotionTrend: 'stable',
      signals: Array.from({ length: 12 }, (_, index) => ({
        ...incident.signals[0], alertId: `wait-${index}`, riskType: 'response_wait',
      })) }
    api.risks.mockResolvedValue([record])
    renderPage()
    const button = await screen.findByTestId('risk-open-incident-1')
    const row = button.closest('tr')!
    expect(within(row).getAllByText('未回复预警')).toHaveLength(1)
    expect(within(row).getByText('持续激烈')).toBeInTheDocument()
    expect(within(row).queryByText('稳定')).not.toBeInTheDocument()
    expect(within(row).getByText('中风险')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '判断待审' })).not.toBeInTheDocument()
  })

  it('所有风险可直接跳到明确的主会话，不取字典序第一条', async () => {
    const user = userEvent.setup()
    api.risks.mockResolvedValue([{ ...incident, conversationIds: ['conv-old', 'conv-latest'],
      primaryConversationId: undefined }])
    renderPage()
    await user.click(await screen.findByRole('button', { name: '打开会话 消费者甲' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/support?conversation=conv-old')
    expect(api.intervene).not.toHaveBeenCalled()
    expect(api.analyze).not.toHaveBeenCalled()
  })

  it('模型核验原文不泄漏到错误提示', async () => {
    const user = userEvent.setup()
    api.analyze.mockRejectedValueOnce(new ApiError(400, 'model_output_invalid', '服务断点分析未通过',
      'draft.service_breakpoints为空数组，内部核验详情'))
    renderPage()
    await openBreakpoints(user)
    await user.click(screen.getByRole('button', { name: '分析服务断点' }))
    expect(await screen.findByText('分析结果暂不可用，请重试')).toBeInTheDocument()
    expect(screen.queryByText(/draft.service_breakpoints/)).not.toBeInTheDocument()
  }, 15000)

  it.each([
    ['angry', 'stable', '持续激烈'], ['dissatisfied', 'stable', '持续不满'],
    ['calm', 'stable', '平稳'], ['calm', 'unknown', '平稳'], ['angry', 'rising', '激烈 · 加剧'],
    ['dissatisfied', 'falling', '不满 · 缓和'],
  ] as const)('情绪程度%s趋势%s显示%s', (currentEmotion, emotionTrend, label) => {
    expect(emotionStatus({ currentEmotion, emotionTrend })).toBe(label)
  })
})
