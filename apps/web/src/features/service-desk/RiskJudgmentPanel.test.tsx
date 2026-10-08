import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type RiskIncidentDetailView, type RiskJudgmentView } from '../../api/client'
import { RiskJudgmentPanel } from './RiskJudgmentPanel'

const api = vi.hoisted(() => ({ judge: vi.fn(), risk: vi.fn() }))
vi.mock('../../api/client', async (original) => {
  const actual = await original<typeof import('../../api/client')>()
  return { ...actual, deskApi: { ...actual.deskApi, judgeRisk: api.judge, risk: api.risk } }
})

const detail: RiskIncidentDetailView = {
  incident: {
    incidentId: 'incident-1', buyerAlias: '消费者甲', conversationIds: ['conv-1'], orderIds: [],
    workOrderIds: [], riskLevel: 'high', riskStatus: 'pending', latestMessage: '我要投诉',
    updatedAt: '2026-10-02T08:00:00Z', recommendedAction: '核对诉求', openTicketCount: 0,
    needsReview: false, recurrenceCount: 0, signalActive: true, version: 'version-1', judgments: [],
    triageScore: 80, triageLabel: 'urgent', triageReasons: ['高风险'], historicalSensitivity: 0, attentionState: 'active',
    currentEmotion: 'angry', emotionTrend: 'rising', serviceState: 'live', currentAction: 'intervene',
    signals: [{ alertId: 'signal-1', conversationId: 'conv-1', buyerAlias: '消费者甲',
      riskType: 'complaint_risk', riskStatus: 'pending', evidenceRefs: ['m1'],
      riskLevel: 'high', triggerSummary: '消费者要求投诉', recommendedAction: '核对诉求',
      createdAt: '2026-10-02T08:00:00Z', updatedAt: '2026-10-02T08:00:00Z',
      episode: 1, revision: 1, ruleVersion: 'explicit-fixture', signalActive: true }],
  },
  contexts: [], evidence: [], tickets: [], handlingHistory: [], judgmentHistory: [],
}

const judgment: RiskJudgmentView = {
  judgmentId: 'judgment-1', alertId: 'signal-1', episode: 1, verdict: 'false_positive',
  actor: 'G002', note: '原文为客服说明，不是消费者投诉', createdAt: '2026-10-02T09:00:00Z',
  stale: true, riskType: 'complaint_risk', riskLevel: 'high', ruleVersion: 'explicit-fixture',
  conversationId: 'conv-1', orderIds: [], workOrderIds: [], evidenceRefs: ['m1'], conditions: {},
  signalActive: true, detectionHash: 'explicit-fixture-hash', triggerSummary: '消费者要求投诉',
  evidence: [{ ref: 'm1', kind: 'message', label: '消费者原文', body: '我要投诉' }],
}

beforeEach(() => {
  vi.clearAllMocks()
  api.judge.mockResolvedValue(detail)
  api.risk.mockResolvedValue(detail)
})

function mount(value = detail) {
  const onChange = vi.fn()
  const result = render(<ConfigProvider><RiskJudgmentPanel detail={value} onChange={onChange} /></ConfigProvider>)
  return { ...result, onChange }
}

describe('风险判断复核', () => {
  it('必须填写依据，误报判断不触发风险关闭', async () => {
    const user = userEvent.setup()
    const { onChange } = mount()
    await user.click(screen.getByTestId('risk-judge-signal-1'))
    expect(screen.getByRole('button', { name: '保存判断' })).toBeDisabled()
    await user.click(screen.getByText('误报', { exact: true }))
    await user.type(screen.getByRole('textbox', { name: '判断依据' }), '引用内容来自另一个事项')
    await user.click(screen.getByRole('button', { name: '保存判断' }))
    await waitFor(() => expect(api.judge).toHaveBeenCalledOnce())
    expect(api.judge).toHaveBeenCalledWith('incident-1', 'signal-1', {
      verdict: 'false_positive', note: '引用内容来自另一个事项',
      expectedVersion: 'version-1', expectedJudgmentId: null,
    })
    expect(onChange).toHaveBeenCalledWith(detail)
    expect(detail.incident.riskStatus).toBe('pending')
  }, 15000)

  it('展示过期判断与原始证据，修订携带前一版ID', async () => {
    const user = userEvent.setup()
    mount({ ...detail, incident: { ...detail.incident, judgments: [judgment] },
      judgmentHistory: [judgment] } as RiskIncidentDetailView)
    expect(screen.getByText('待重审')).toBeInTheDocument()
    expect(screen.getByText('依据已变化')).toBeInTheDocument()
    await user.click(screen.getByText('证据快照'))
    expect(await screen.findByText('我要投诉')).toBeInTheDocument()
    await user.click(screen.getByTestId('risk-judge-signal-1'))
    await user.type(screen.getByRole('textbox', { name: '判断依据' }), '补充核对最新原文')
    await user.click(screen.getByRole('button', { name: '保存判断' }))
    await waitFor(() => expect(api.judge).toHaveBeenCalledOnce())
    expect(api.judge.mock.calls[0][2].expectedJudgmentId).toBe('judgment-1')
  }, 15000)

  it('保存冲突回读新版本', async () => {
    const user = userEvent.setup()
    const { onChange } = mount()
    api.judge.mockRejectedValueOnce(new ApiError(409, 'conflict', '判断记录已更新', null))
    await user.click(screen.getByTestId('risk-judge-signal-1'))
    await user.type(screen.getByRole('textbox', { name: '判断依据' }), '人工核对')
    await user.click(screen.getByRole('button', { name: '保存判断' }))
    expect(await screen.findByText('判断记录已更新')).toBeInTheDocument()
    await waitFor(() => expect(api.risk).toHaveBeenCalledWith('incident-1'))
    expect(onChange).toHaveBeenCalledWith(detail)
  }, 15000)

  it('普通保存失败保留判断依据和已有记录', async () => {
    const user = userEvent.setup()
    api.judge.mockRejectedValueOnce(new Error('保存失败'))
    const { onChange } = mount()
    await user.click(screen.getByTestId('risk-judge-signal-1'))
    await user.type(screen.getByRole('textbox', { name: '判断依据' }), '已核对原始记录')
    await user.click(screen.getByRole('button', { name: '保存判断' }))
    expect(await screen.findByText('保存失败')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '判断依据' })).toHaveValue('已核对原始记录')
    expect(onChange).not.toHaveBeenCalled()
    expect(api.risk).not.toHaveBeenCalled()
  }, 15000)

  it('切换事件后迟到保存结果不能回写新事件', async () => {
    const user = userEvent.setup()
    let resolve!: (value: RiskIncidentDetailView) => void
    api.judge.mockReturnValue(new Promise<RiskIncidentDetailView>((done) => { resolve = done }))
    const { onChange, unmount } = mount()
    await user.click(screen.getByTestId('risk-judge-signal-1'))
    await user.type(screen.getByRole('textbox', { name: '判断依据' }), '核对原文')
    await user.click(screen.getByRole('button', { name: '保存判断' }))
    unmount()
    resolve(detail)
    await waitFor(() => expect(onChange).not.toHaveBeenCalled())
  }, 15000)
})
