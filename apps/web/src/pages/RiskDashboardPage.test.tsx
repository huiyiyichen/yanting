import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RiskDashboardPage } from './RiskDashboardPage'

const api = vi.hoisted(() => ({
  risks: vi.fn(), reception: vi.fn(), risk: vi.fn(), analyze: vi.fn(), operators: vi.fn(), intervene: vi.fn(), judge: vi.fn(), score: vi.fn(),
}))

vi.mock('../api/client', async (original) => {
  const actual = await original<typeof import('../api/client')>()
  return {
    ...actual,
    deskApi: { ...actual.deskApi, risks: api.risks, risk: api.risk, analyzeBreakpoints: api.analyze, operators: api.operators,
      interveneRisk: api.intervene, judgeRisk: api.judge, conversationScore: api.score },
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
  api.score.mockImplementation(async (cid: string) => ({ conversationId: cid, waits: [], breaks: [], notes: [
    { messageId: 'm1', at: '2026-05-11T10:18:00+08:00', role: 'customer', body: '查不出来我就去平台举报', level: 'angry', signals: ['complaint_risk'], highlights: [] },
    { messageId: 'm2', at: '2026-05-11T10:25:00+08:00', role: 'customer', body: '嗯，这还差不多', level: 'calm', signals: [], highlights: [] },
  ] }))
  api.operators.mockResolvedValue({ defaultOperatorId: 'G001', operators: [{ operatorId: 'G001', name: '模拟客服 G001' }] })
})

function renderPage(path = '/risk') {
  return render(<ConfigProvider><MemoryRouter initialEntries={[path]}><RiskDashboardPage /><Location /></MemoryRouter></ConfigProvider>)
}

function Location() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
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
    expect(screen.getByRole('radio', { name: '官方记录' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.queryByTestId('risk-open-incident-1')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '打开会话 雷**' }))
    expect(screen.getByTestId('location')).toHaveTextContent('/support?conversation=S00146')
  })

  /** F 队列行：长昵称无全称提示、缺迷你声纹、状态不是胶囊。 */
  it('队列行显示迷你声纹与状态胶囊，长昵称单行并悬停显示全称', async () => {
    api.risks.mockResolvedValue([{ ...incident, buyerAlias: '一个特别特别长的消费者昵称**', emotionSeq: ['c0', 'o', 'c1'] }])
    renderPage()
    await screen.findByTestId('risk-open-incident-1')
    expect(screen.getByRole('img', { name: /^情绪序列/ })).toBeInTheDocument()
    expect(screen.getByTitle('一个特别特别长的消费者昵称**')).toHaveClass('yt-rk-name')
    expect(document.querySelector('.yt-rk-status')).not.toBeNull()
  })

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

  it('F4 抽屉/详情可用 Esc 关闭，输入框内按 Esc 不关闭', async () => {
    const user = userEvent.setup()
    api.risks.mockResolvedValue([incident])
    api.risk.mockResolvedValue(detail)
    renderPage()
    await user.click(await screen.findByTestId('risk-open-incident-1'))
    expect(await screen.findByRole('complementary', { name: '风险详情' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('complementary', { name: '风险详情' })).not.toBeInTheDocument())
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
    renderPage('/risk?conversation=conv-1')
    await waitFor(() => expect(api.risk).toHaveBeenCalledWith('incident-1'))
    await screen.findByRole('heading', { name: '消费者甲' })
    // 全景方案 4.12 F1：同一会话情绪只在“对话回放”一处；结论、三个页签
    expect(await screen.findByRole('region', { name: '风险结论' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '情绪轨迹' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '情绪弧线' })).not.toBeInTheDocument()
    expect(await screen.findByText('嗯，这还差不多')).toBeInTheDocument()
    // 用户反馈 10-18 #7：去掉“处置记录”页签，只留对话回放、服务轨迹
    expect(screen.getAllByRole('tab').map((node) => node.textContent)).toEqual(expect.arrayContaining(['对话回放', '服务轨迹']))
    expect(screen.queryByRole('tab', { name: '处置记录' })).toBeNull()
    expect(screen.getByRole('radio', { name: '官方记录' })).toHaveAttribute('aria-checked', 'true')
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

  it('F5 范围只在顶部切换；页签为 待处理/待复核/已关闭/全部；点行打开详情，无“详情”按钮', async () => {
    const user = userEvent.setup()
    api.risks.mockResolvedValue([incident])
    api.risk.mockResolvedValue(detail)
    renderPage()
    const tabs = (await screen.findAllByRole('tab')).map((node) => node.textContent?.replace(/\s*\d+$/, ''))
    expect(tabs).toEqual(['待处理', '待复核', '已关闭', '全部'])
    expect(screen.queryByRole('button', { name: /详情/ })).not.toBeInTheDocument()
    await user.click(await screen.findByText('消费者甲'))
    expect(await screen.findByRole('complementary', { name: '风险详情' })).toBeInTheDocument()
  }, 15000)
})
