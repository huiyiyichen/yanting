import type { ProductClueView, RiskOverviewView } from '../../api/client'
import { serviceRiskTypeLabels } from '../../contracts/enums'

const LEVEL_LABELS: Record<string, string> = { high: '高', medium: '中', low: '低' }
const typeLabel = (key: string) => (serviceRiskTypeLabels as Record<string, string>)[key] ?? key

/**
 * 情绪声纹·分布（5.4.3 distribution）：严格按数量绘制。
 * 中线以上堆叠不满（橙）与激烈（红），中线以下画平稳（绿）；上方标记带画高风险会话菱形。
 */
function DistributionVoiceprint({ overview, onMarker }: {
  overview: RiskOverviewView; onMarker: (conversationId: string) => void
}) {
  const buckets = overview.hourly
  const max = Math.max(1, ...buckets.map((b) => Math.max(b.dissatisfied + b.angry, b.calm)))
  const barW = 5, gap = 2, top = 18, half = 46
  const width = Math.max(240, buckets.length * (barW + gap) + 8)
  const mid = top + half
  const negative = buckets.reduce((sum, b) => sum + b.dissatisfied + b.angry, 0)
  const index = new Map(buckets.map((b, i) => [`${b.date}-${b.hour}`, i]))
  const peak = buckets.reduce((best, b, i) => (b.dissatisfied + b.angry > (best.v ?? -1) ? { i, v: b.dissatisfied + b.angry } : best), { i: -1, v: -1 })
  const summary = `情绪声纹：消费者消息 ${overview.customerMessages} 条，负面 ${negative} 条，高风险会话 ${overview.highRiskMarkers.length} 个`
  let lastDate = ''
  return <div className="yt-dist">
    <svg role="img" aria-label={summary} width={width} height={mid + half + 6} viewBox={`0 0 ${width} ${mid + half + 6}`}>
      <line x1={0} x2={width} y1={mid} y2={mid} className="yt-dist-mid" />
      {buckets.map((b, i) => {
        const x = 4 + i * (barW + gap)
        const scale = (n: number) => (n / max) * (half - 4)
        const upset = scale(b.dissatisfied), angry = scale(b.angry), calm = scale(b.calm)
        const divider = b.date !== lastDate && i > 0
        lastDate = b.date
        return <g key={`${b.date}-${b.hour}`}>
          {divider && <line x1={x - gap / 2} x2={x - gap / 2} y1={top} y2={mid + half} className="yt-dist-day" />}
          <title>{`${b.date} ${b.hour}时 平稳 ${b.calm} · 不满 ${b.dissatisfied} · 激烈 ${b.angry}`}</title>
          {upset > 0 && <rect x={x} y={mid - upset} width={barW} height={upset} className="yt-dist-upset" />}
          {angry > 0 && <rect x={x} y={mid - upset - angry - (upset > 0 ? 2 : 0)} width={barW} height={angry} className="yt-dist-fury" />}
          {calm > 0 && <rect x={x} y={mid + 1} width={barW} height={calm} className="yt-dist-calm" />}
        </g>
      })}
      {peak.i >= 0 && peak.v > 0 && <text x={4 + peak.i * (barW + gap)} y={top - 4} className="yt-dist-peak">
        {buckets[peak.i].hour}时 {peak.v}
      </text>}
    </svg>
    <div className="yt-dist-markers" style={{ width }}>
      {overview.highRiskMarkers.map((m) => {
        const i = index.get(`${m.date}-${m.hour}`)
        if (i === undefined) return null
        return <button key={m.conversationId} type="button" className="yt-dist-marker"
          style={{ left: 4 + i * (barW + gap) - 3 }} title={`${m.alias} · ${m.types.map(typeLabel).join('、')}`}
          aria-label={`${m.alias} ${m.conversationId}`} onClick={() => onMarker(m.conversationId)} />
      })}
    </div>
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
        <div className="yt-kpi" aria-label="风险事件"><span>风险事件</span><strong>{counts.events}</strong></div>
        <div className="yt-kpi" aria-label="风险信号"><span>风险信号</span><strong>{counts.signals}</strong></div>
        <div className="yt-kpi" aria-label="情绪升级"><span>情绪升级</span><strong>{counts.emotionEscalation}</strong></div>
        <div className="yt-kpi" aria-label="不良反应"><span>不良反应</span><strong>{counts.adverseReaction}</strong></div>
      </div>
      <div className="yt-dist-wrap">
        <div className="yt-panel-head"><h3>情绪声纹</h3>
          <span>{overview.hourly[0]?.date.slice(5)}–{overview.hourly.at(-1)?.date.slice(5)} · {overview.customerMessages} 条 · 负面 {Math.round(overview.negativeShare * 100)}%</span>
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
          <i className={`is-${key}`} />{LEVEL_LABELS[key]} {overview.levels[key] ?? 0}</li>)}</ul>
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
