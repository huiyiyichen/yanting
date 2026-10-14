import type { ReactElement } from 'react'
/**
 * 情绪声纹（改进方案 5.4.3）。conversation：插件客户卡；mini：风险队列行。
 * 消费者消息画对称竖条，峰值高度 = 情绪等级；服务回复是中线上的金色圆点。
 * 只有峰值高度承载数据，对称是品牌表达；颜色之外 aria-label 给出文字摘要。
 */
export type VoiceprintPoint = { at: string; role: string; level?: string | null }

const LEVEL_HEIGHT: Record<string, [number, number]> = {
  calm: [7, 5], dissatisfied: [15, 12], angry: [24, 20],
}
const LEVEL_LABEL: Record<string, string> = { calm: '平稳', dissatisfied: '不满', angry: '激烈' }

export function voiceprintSummary(points: VoiceprintPoint[]): string {
  const customer = points.filter((point) => point.role === 'customer' && point.level)
  const counts = ['calm', 'dissatisfied', 'angry']
    .map((level) => [LEVEL_LABEL[level], customer.filter((point) => point.level === level).length] as const)
    .filter(([, count]) => count > 0)
    .map(([label, count]) => `${label} ${count}`)
  const service = points.filter((point) => point.role !== 'customer').length
  return `情绪声纹：消费者消息 ${customer.length} 条（${counts.join('、') || '无'}），服务回复 ${service} 条`
}

export function Voiceprint({ points, variant = 'conversation', width }: {
  points: VoiceprintPoint[]; variant?: 'conversation' | 'mini'; width?: number
}) {
  const mini = variant === 'mini'
  const height = mini ? 24 : 52
  const mid = height / 2
  const shown = points.filter((point) => point.role !== 'system')
  const step = mini ? 7 : 16
  const total = width ?? Math.max(mini ? 132 : 120, shown.length * step + 8)
  const bars: ReactElement[] = []
  let escalationStart: number | null = null
  let previous: string | null | undefined
  shown.forEach((point, index) => {
    const x = 6 + index * step
    if (point.role !== 'customer') {
      bars.push(<circle key={index} cx={x} cy={mid} r={mini ? 1.6 : 2.4} className="yt-vp-service" />)
      return
    }
    const level = point.level ?? 'calm'
    if (level === 'angry' && previous && previous !== 'angry' && escalationStart === null) escalationStart = x - step / 2
    previous = level
    const peak = LEVEL_HEIGHT[level]?.[mini ? 1 : 0] ?? 5
    if (mini) {
      bars.push(<rect key={index} x={x - 1.5} y={mid - peak / 2} width={3} height={peak} rx={1.5}
        className={`yt-vp-bar is-${level}`} />)
      return
    }
    // 7 根对称竖条，中间最高
    const shape = [0.3, 0.55, 0.8, 1, 0.8, 0.55, 0.3]
    shape.forEach((ratio, offset) => {
      const h = Math.max(2, peak * ratio)
      bars.push(<rect key={`${index}-${offset}`} x={x - 6 + offset * 2} y={mid - h / 2} width={1.4} height={h}
        rx={0.7} className={`yt-vp-bar is-${level}`} />)
    })
  })
  return <svg className={`yt-voiceprint is-${variant}`} role="img" aria-label={voiceprintSummary(shown)}
    width={total} height={height} viewBox={`0 0 ${total} ${height}`}>
    {escalationStart !== null && <rect x={escalationStart} y={0} width={total - escalationStart} height={height}
      className="yt-vp-escalation" />}
    <line x1={0} x2={total} y1={mid} y2={mid} className="yt-vp-mid" />
    {bars}
  </svg>
}
