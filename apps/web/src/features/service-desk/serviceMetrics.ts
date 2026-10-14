import type { ReceptionStatsView } from '../../api/client'

type Stat = { label: string; value: number | string; warning?: boolean }

const percent = (value?: number | null) => (value == null ? '—' : `${Math.round(value * 100)}%`)
const duration = (seconds?: number | null) => {
  if (seconds == null) return '—'
  return seconds < 60 ? `${Math.round(seconds)} 秒` : `${(seconds / 60).toFixed(1)} 分`
}

/** 客服工作台顶栏六项服务指标；口径见后端 service_metrics。 */
export function serviceMetricStats(metrics: ReceptionStatsView | null): Stat[] {
  if (!metrics) return ['AI 接待', '自动回复率', '转人工', '平均首响', '建议采纳率', '待处理风险'].map((label) => ({ label, value: '—' }))
  return [
    { label: 'AI 接待', value: metrics.aiConversations ?? 0 },
    { label: '自动回复率', value: percent(metrics.autoReplyRate) },
    { label: '转人工', value: metrics.handoffs?.total ?? 0 },
    { label: '平均首响', value: duration(metrics.averageFirstResponseSeconds) },
    { label: '建议采纳率', value: percent(metrics.suggestionAdoptionRate) },
    { label: '待处理风险', value: metrics.pendingRisks, warning: metrics.pendingRisks > 0 },
  ]
}
