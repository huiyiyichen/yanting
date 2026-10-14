/**
 * 顶栏指标格式（P1-9）。失败方式：
 * T1 无数据时显示 0% 或 0 秒（应显示“—”）。
 * T2 百分比与时长格式不统一（率显示整数百分比，首响 <60 秒显示秒、否则显示分）。
 * T3 六项指标缺项或顺序与方案不一致。
 */
import { describe, expect, it } from 'vitest'
import { serviceMetricStats } from './serviceMetrics'

const filled = {
  aiConversations: 12, autoReplyRate: 0.6667, handoffs: { total: 4, customer: 2, safety: 1, modelFailure: 1 },
  averageFirstResponseSeconds: 95, suggestionAdoptionRate: 0.5, liveConversations: 3,
  historicalConversations: 138, unreadMessages: 0, openTickets: 1, pendingRisks: 7,
}

describe('serviceMetricStats', () => {
  it('T3 keeps six metrics in order', () => {
    expect(serviceMetricStats(filled).map((item) => item.label)).toEqual(
      ['AI 接待', '自动回复率', '转人工', '平均首响', '建议采纳率', '待处理风险'])
  })
  it('T2 formats rates and durations', () => {
    const values = serviceMetricStats(filled).map((item) => item.value)
    expect(values).toEqual([12, '67%', 4, '1.6 分', '50%', 7])
    expect(serviceMetricStats({ ...filled, averageFirstResponseSeconds: 42.4 })[3].value).toBe('42 秒')
  })
  it('T1 shows a dash without data', () => {
    const values = serviceMetricStats({ ...filled, autoReplyRate: null, averageFirstResponseSeconds: null,
      suggestionAdoptionRate: null }).map((item) => item.value)
    expect(values[1]).toBe('—'); expect(values[3]).toBe('—'); expect(values[4]).toBe('—')
    expect(serviceMetricStats(null).every((item) => item.value === '—')).toBe(true)
  })
})
