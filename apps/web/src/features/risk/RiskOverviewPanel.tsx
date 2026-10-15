import { useState } from 'react'
import type { ProductClueView, RiskOverviewView } from '../../api/client'
import { serviceRiskTypeLabels } from '../../contracts/enums'

const LEVEL_LABELS: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }
const typeLabel = (key: string) => (serviceRiskTypeLabels as Record<string, string>)[key] ?? key

/**
 * 情绪声纹·分布（5.4.3 distribution）：严格按数量绘制，按概念稿的比例与节奏。
 * 每天取固定时段（数据中出现过的最早到最晚小时）铺满格子，空小时留白而不是被挤掉；
 * 中线以上不满（琥珀）与激烈（红）分段堆叠、段间留 2px，中线以下平稳（绿，半透明），上下各自按最大值缩放；
 * 圆角柱、等比缩放（不拉伸），上方一条带画高风险会话菱形，只标注一个负面峰值；悬停整列高亮并显示该小时数量。
 */
function DistributionVoiceprint({ overview, onMarker }: {
  overview: RiskOverviewView; onMarker: (conversationId: string) => void
}) {
  const [hover, setHover] = useState<number | null>(null)
  const buckets = overview.hourly
  const days = [...new Set(buckets.map((b) => b.date))].sort()
  const hours = buckets.map((b) => b.hour)
  const h0 = Math.min(8, ...hours), h1 = Math.max(23, ...hours)
  // 天数多时按 2 小时合并，保证柱宽不细成线
  const step = days.length > 10 ? 2 : 1
  const perDay = Math.ceil((h1 - h0 + 1) / step)
  const slots = days.flatMap((date) => Array.from({ length: perDay }, (_, k) => ({ date, hour: h0 + k * step, calm: 0, dissatisfied: 0, angry: 0 })))
  for (const b of buckets) {
    const slot = slots[days.indexOf(b.date) * perDay + Math.floor((b.hour - h0) / step)]
    if (slot) { slot.calm += b.calm; slot.dissatisfied += b.dissatisfied; slot.angry += b.angry }
  }
  const W = 1080, H = 214, top = 26, bottomPad = 24
  const maxUp = Math.max(1, ...slots.map((b) => b.dissatisfied + b.angry))
  const maxDown = Math.max(1, ...slots.map((b) => b.calm))
  const u = (H - top - bottomPad) / (maxUp + maxDown + 1)
  const mid = top + (maxUp + 0.5) * u
  const slot = W / Math.max(1, slots.length)
  const bw = Math.max(2, Math.min(6, slot - 2))
  const negative = buckets.reduce((sum, b) => sum + b.dissatisfied + b.angry, 0)
  const summary = `情绪声纹：消费者消息 ${overview.customerMessages} 条，负面 ${negative} 条，高风险会话 ${overview.highRiskMarkers.length} 个`
  const peakIndex = slots.reduce((best, b, i) => (b.dissatisfied + b.angry > slots[best].dissatisfied + slots[best].angry ? i : best), 0)
  const peak = slots[peakIndex]
  const xOf = (i: number) => i * slot + (slot - bw) / 2
  const indexOf = (date: string, hour: number) => days.indexOf(date) * perDay + Math.floor((hour - h0) / step)
  const hovered = hover === null ? null : slots[hover]
  return <div className="yt-dist">
    <svg role="img" aria-label={summary} viewBox={`0 0 ${W} ${H}`} width="100%" onMouseLeave={() => setHover(null)}
      onMouseMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect()
        const k = Math.floor(((event.clientX - box.left) / box.width) * W / slot)
        setHover(Math.max(0, Math.min(slots.length - 1, k)))
      }}>
      {days.map((date, di) => <g key={date}>
        {di > 0 && <line x1={di * perDay * slot} x2={di * perDay * slot} y1={top - 4} y2={H - bottomPad + 6} className="yt-dist-day" />}
        <text x={di * perDay * slot + 6} y={H - 6} className="yt-dist-date">{date.slice(5).replace('-', '/')}</text>
      </g>)}
      <line x1={0} x2={W} y1={mid} y2={mid} className="yt-dist-mid" />
      {hover !== null && <rect x={hover * slot} y={top - 6} width={slot} height={H - top - bottomPad + 12} rx={3} className="yt-dist-hover" />}
      {slots.map((b, i) => {
        const x = xOf(i)
        const delay = { animationDelay: `${(i * 0.004).toFixed(3)}s` }
        return <g key={`${b.date}-${b.hour}`}>
          {b.calm > 0 && <rect x={x} y={mid + 2} width={bw} height={b.calm * u} rx={2} className="yt-dist-calm yt-dist-bar is-down" style={delay} />}
          {b.dissatisfied > 0 && <rect x={x} y={mid - 2 - b.dissatisfied * u} width={bw} height={b.dissatisfied * u} rx={2} className="yt-dist-upset yt-dist-bar" style={delay} />}
          {b.angry > 0 && <rect x={x} y={mid - 2 - b.dissatisfied * u - (b.dissatisfied ? 2 : 0) - b.angry * u} width={bw} height={b.angry * u} rx={2}
            className="yt-dist-fury yt-dist-bar" style={delay} />}
        </g>
      })}
      {peak && peak.dissatisfied + peak.angry > 0 && <text x={xOf(peakIndex) + bw + 6}
        y={mid - 2 - (peak.dissatisfied + peak.angry) * u - (peak.angry && peak.dissatisfied ? 2 : 0) + 4} className="yt-dist-peak">
        {peak.date.slice(5).replace('-', '/')} {peak.hour}时{step > 1 ? '起' : ''} 负面 {peak.dissatisfied + peak.angry}
      </text>}
    </svg>
    <div className="yt-dist-markers">
      {overview.highRiskMarkers.map((m) => {
        const i = indexOf(m.date, m.hour)
        if (days.indexOf(m.date) < 0) return null
        return <button key={m.conversationId} type="button" className="yt-dist-marker"
          style={{ left: `${((i * slot + slot / 2) / W) * 100}%` }} title={`${m.alias} · ${m.types.map(typeLabel).join('、')}`}
          aria-label={`${m.alias} ${m.conversationId}`} onClick={() => onMarker(m.conversationId)} />
      })}
    </div>
    {hovered && hover !== null && <div className="yt-dist-tip" style={{ left: `${((hover * slot + slot / 2) / W) * 100}%` }}>
      <b>{hovered.date.slice(5).replace('-', '/')} {step > 1 ? `${hovered.hour}–${hovered.hour + step}时` : `${hovered.hour}时`}</b>
      <span><i className="is-fury" />激烈 {hovered.angry}</span><span><i className="is-upset" />不满 {hovered.dissatisfied}</span>
      <span><i className="is-calm" />平稳 {hovered.calm}</span>
    </div>}
  </div>
}

export function RiskOverviewPanel({ overview, clues, onFilterType, onFilterConversation }: {
  overview: RiskOverviewView; clues: ProductClueView[]
  onFilterType: (type: string) => void; onFilterConversation: (conversationId: string) => void
}) {
  const { counts } = overview
  const levelTotal = Math.max(1, Object.values(overview.levels).reduce((a, b) => a + b, 0))
  const typeRows = Object.entries(overview.types).sort((a, b) => b[1] - a[1])
  const typeMax = Math.max(1, ...typeRows.map(([, v]) => v))
  return <section className="yt-monitor" aria-label="风险总览">
    <div className="yt-monitor-hero">
      <div className="yt-kpis">
        <div className="yt-kpi is-main" aria-label="待处理"><span>待处理</span><strong>{counts.pending}</strong></div>
        <div className="yt-kpi" aria-label="高风险"><span>高风险</span><strong className="is-fury">{counts.high}</strong></div>
        <div className="yt-kpi" aria-label="风险事件"><span>风险事件</span><strong>{counts.events}</strong>
          <small aria-label="风险信号">信号 {counts.signals}</small></div>
        <div className="yt-kpi" aria-label="情绪升级"><span>情绪升级</span><strong>{counts.emotionEscalation}</strong></div>
        <div className="yt-kpi" aria-label="不良反应"><span>不良反应</span><strong>{counts.adverseReaction}</strong></div>
      </div>
      <div className="yt-dist-wrap">
        <div className="yt-panel-head"><h3>情绪声纹</h3>
          <span className="yt-num">{overview.hourly[0]?.date.slice(5).replace('-', '/')}–{overview.hourly.at(-1)?.date.slice(5).replace('-', '/')}</span>
          <span>消费者消息 <b>{overview.customerMessages}</b> 负面 <b>{Math.round(overview.negativeShare * 100)}%</b></span>
          <span className="yt-legend"><i className="is-fury" />激烈<i className="is-upset" />不满<i className="is-calm" />平稳<i className="is-marker" />高风险会话</span>
        </div>
        <DistributionVoiceprint overview={overview} onMarker={onFilterConversation} />
      </div>
    </div>
    <div className="yt-monitor-grid">
      <div className="yt-panel"><div className="yt-panel-head"><h3>风险等级</h3></div>
        <div className="yt-level-bar">{(['high', 'medium', 'low'] as const).map((key) => overview.levels[key] ? <span key={key}
          className={`is-${key}`} style={{ flexGrow: overview.levels[key] / levelTotal }} /> : null)}</div>
        <ul className="yt-level-legend">{(['high', 'medium', 'low'] as const).map((key) => <li key={key}>
          <i className={`is-${key}`} />{LEVEL_LABELS[key]}<b>{overview.levels[key] ?? 0}</b></li>)}</ul>
      </div>
      <div className="yt-panel"><div className="yt-panel-head"><h3>风险类型</h3></div>
        <ul className="yt-type-bars">{typeRows.map(([key, value]) => <li key={key}>
          <button type="button" onClick={() => onFilterType(key)} aria-label={`${typeLabel(key)} ${value}`}>
            <span className="yt-type-name">{typeLabel(key)}</span>
            <span className="yt-type-track"><span style={{ width: `${(value / typeMax) * 100}%` }} /></span>
            <span className="yt-type-value">{value}</span>
          </button></li>)}</ul>
      </div>
      <div className="yt-panel"><div className="yt-panel-head"><h3>商品风险线索</h3></div>
        <ul className="yt-clues">{clues.slice(0, 4).map((clue) => <li key={clue.productName}>
          <strong title={clue.productName}>{clue.productName}</strong>
          <span className="yt-clue-tags">
            <em>不良反应 {clue.adverseReactions}</em>
            {clue.medicalVisits > 0 && <em className="is-fury">就医 {clue.medicalVisits}</em>}
            <em>关联工单 {clue.relatedTickets}</em>
            {clue.batches.length > 0 && <em title={clue.batches.join('、')}>批次 {clue.batches.length}</em>}
          </span>
        </li>)}</ul>
      </div>
    </div>
  </section>
}
