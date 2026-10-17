import { Popover } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { shMonthDay } from '../service-desk/shTime'
import { axisBreaks, dailyTotals, daysIn, densestWindow, shiftRange, windowFrom } from './distDays'
import type { DateRange, ProductClueView, RiskOverviewView } from '../../api/client'
import { serviceRiskTypeLabels } from '../../contracts/enums'

const LEVEL_LABELS: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险' }
const typeLabel = (key: string) => (serviceRiskTypeLabels as Record<string, string>)[key] ?? key

/**
 * 情绪声纹·分布（5.4.3 distribution）：严格按数量绘制，按概念稿的比例与节奏。
 * 每天取固定时段（数据中出现过的最早到最晚小时）铺满格子，空小时留白而不是被挤掉；
 * 中线以上不满（琥珀）与激烈（红）分段堆叠、段间留 2px，中线以下平稳（绿，半透明），上下各自按最大值缩放；
 * 圆角柱、等比缩放（不拉伸），上方一条带画高风险会话菱形，只标注一个负面峰值；悬停整列高亮并显示该小时数量。
 */
const STACK_GAP = 1

/** 每根柱合并几个小时：柱子总数尽量不超过 60。 */
export function mergeStep(dayCount: number, hoursPerDay: number, maxBars = 60): number {
  return [1, 2, 3, 4, 6, 8].find((step) => dayCount * Math.ceil(hoursPerDay / step) <= maxBars) ?? 12
}

/** X-1 缩略条：全部日期每天一格，高度=负面条数，亮框为当前显示的 7 天；点某天把窗口移到那天起。 */
function DistOverview({ overview, shown, onPick, onShift }: {
  overview: RiskOverviewView; shown: string[]; onPick: (date: string) => void; onShift: (days: number) => void
}) {
  const rows = dailyTotals(overview.hourly)
  const max = Math.max(1, ...rows.map((r) => r.negative))
  return <div className="yt-dist-overview" role="group" aria-label="声纹缩略条"
    onKeyDown={(event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
      event.preventDefault(); onShift((event.key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 7 : 1))
    }}>
    {rows.map((r) => <button type="button" key={r.date} aria-pressed={shown.includes(r.date)}
      aria-label={`${r.date.slice(5).replace('-', '/')} 负面 ${r.negative}`} onClick={() => onPick(r.date)}>
      <i style={{ height: `${Math.max(8, (r.negative / max) * 100)}%` }} /></button>)}
  </div>
}

function DistributionVoiceprint({ overview, days, hot, onMarker, onBrush }: {
  overview: RiskOverviewView; days: string[]; hot?: string | null
  onMarker: (conversationId: string) => void; onBrush: (range: DateRange | null) => void
}) {
  const [hover, setHover] = useState<number | null>(null)
  const [drag, setDrag] = useState<{ a: number; b: number } | null>(null)
  const breaks = axisBreaks(days)
  const buckets = overview.hourly.filter((b) => days.includes(b.date))
  const hours = buckets.map((b) => b.hour)
  const h0 = Math.min(8, ...hours), h1 = Math.max(23, ...hours)
  // 柱子总数控制在约 60 根以内：按 1/2/3/4/6 小时合并，柱宽才不会细成线、挤成一团
  const step = mergeStep(days.length, h1 - h0 + 1)
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
  const bw = Math.max(3, Math.min(12, slot * 0.62))
  // 激烈直接叠在不满上方，只留 1 个单位的缝；小段圆角随高度收小，避免看起来像分开的点
  const r = (h: number) => Math.min(2, h / 2)
  const negative = buckets.reduce((sum, b) => sum + b.dissatisfied + b.angry, 0)
  const summary = `情绪声纹：消费者消息 ${overview.customerMessages} 条，负面 ${negative} 条，高风险会话 ${overview.highRiskMarkers.length} 个`
  const xOf = (i: number) => i * slot + (slot - bw) / 2
  const indexOf = (date: string, hour: number) => days.indexOf(date) * perDay + Math.floor((hour - h0) / step)
  const hovered = hover === null ? null : slots[hover]
  // 悬停列表行：该会话的高风险标记所在柱提亮，其余降到 40%
  const hotMarker = hot ? overview.highRiskMarkers.find((m) => m.conversationId === hot && days.includes(m.date)) : undefined
  const hotIndex = hotMarker ? indexOf(hotMarker.date, hotMarker.hour) : null
  const slotAt = (event: React.MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect()
    return Math.max(0, Math.min(slots.length - 1, Math.floor(((event.clientX - box.left) / box.width) * W / slot)))
  }
  return <div className={`yt-dist${hotIndex !== null ? ' is-focus' : ''}`}>
    <svg role="img" aria-label={summary} viewBox={`0 0 ${W} ${H}`} width="100%"
      onMouseLeave={() => { setHover(null); setDrag(null) }}
      onMouseDown={(event) => { const k = slotAt(event); setDrag({ a: k, b: k }) }}
      onMouseUp={() => {
        if (drag && drag.a !== drag.b) {
          const [lo, hi] = [Math.min(drag.a, drag.b), Math.max(drag.a, drag.b)]
          onBrush({ from: slots[lo].date, to: slots[hi].date })
        }
        setDrag(null)
      }}
      onDoubleClick={() => onBrush(null)}
      onMouseMove={(event) => {
        const k = slotAt(event)
        setHover(k)
        if (drag) setDrag({ ...drag, b: k })
      }}>
      {days.map((date, di) => <g key={date}>
        {di > 0 && (breaks.has(di)
          ? <text x={di * perDay * slot} y={mid + 4} textAnchor="middle" className="yt-dist-break" aria-label="断档">≈</text>
          : <line x1={di * perDay * slot} x2={di * perDay * slot} y1={top - 4} y2={H - bottomPad + 6} className="yt-dist-day" />)}
        <text x={di * perDay * slot + 6} y={H - 6} className="yt-dist-date">{date.slice(5).replace('-', '/')}</text>
      </g>)}
      <line x1={0} x2={W} y1={mid} y2={mid} className="yt-dist-mid" />
      {drag && drag.a !== drag.b && <rect x={Math.min(drag.a, drag.b) * slot} y={top - 6} width={(Math.abs(drag.b - drag.a) + 1) * slot}
        height={H - top - bottomPad + 12} rx={4} className="yt-dist-brush" />}
      {hover !== null && <rect x={hover * slot} y={top - 6} width={slot} height={H - top - bottomPad + 12} rx={3} className="yt-dist-hover" />}
      {slots.map((b, i) => {
        const x = xOf(i)
        const delay = { animationDelay: `${(i * 0.004).toFixed(3)}s` }
        return <g key={`${b.date}-${b.hour}`} className={i === hotIndex ? 'is-hot' : undefined}>
          {b.calm > 0 && <rect x={x} y={mid + 2} width={bw} height={b.calm * u} rx={r(b.calm * u)} className="yt-dist-calm yt-dist-bar is-down" style={delay} />}
          {b.dissatisfied > 0 && <rect x={x} y={mid - 2 - b.dissatisfied * u} width={bw} height={b.dissatisfied * u} rx={r(b.dissatisfied * u)} className="yt-dist-upset yt-dist-bar" style={delay} />}
          {b.angry > 0 && <rect x={x} y={mid - 2 - b.dissatisfied * u - (b.dissatisfied ? STACK_GAP : 0) - b.angry * u} width={bw} height={b.angry * u} rx={r(b.angry * u)}
            className="yt-dist-fury yt-dist-bar" style={delay} />}
        </g>
      })}
    </svg>
    <div className="yt-dist-markers">
      {overview.highRiskMarkers.map((m) => {
        const i = indexOf(m.date, m.hour)
        if (days.indexOf(m.date) < 0) return null
        return <button key={m.conversationId} type="button" className={`yt-dist-marker${m.conversationId === hot ? ' is-hot' : ''}`}
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

const WORK_TYPE: Record<string, string> = { adverse_reaction: '不良反应', return_refund: '售后退货', reship_exchange: '补发换货', offline_payment: '线下打款', logistics: '物流' }

/** 商品线索展开（全景方案 5.4，反馈 ⑤）：按批次分组列出工单、订单尾号与会话；只列原始记录，不下结论。 */
export function ClueCases({ clue, onFilterConversation }: { clue: ProductClueView; onFilterConversation: (conversationId: string) => void }) {
  const groups = new Map<string, NonNullable<ProductClueView['cases']>>()
  for (const item of clue.cases ?? []) {
    const key = item.batch ? `批次 ${item.batch}` : '其他工单'
    groups.set(key, [...(groups.get(key) ?? []), item])
  }
  return <div className="yt-clue-cases">{[...groups].map(([label, items]) => <section key={label} aria-label={label}>
    <h4>{label}<span>{items.length}</span></h4>
    <ul>{items.map((item) => <li key={item.workOrderId}>
      <span className="d">{shMonthDay(item.createdAt)}</span>
      <span>{WORK_TYPE[item.workOrderType] ?? item.workOrderType}</span>
      <span className="o">{item.orderId ? `订单 …${item.orderId.slice(-4)}` : '无订单'}</span>
      <button type="button" onClick={() => onFilterConversation(item.conversationId)}>{item.buyerAlias} · {item.conversationId}</button>
      <Link to={`/platform/work-orders?q=${encodeURIComponent(item.workOrderId)}`}>{item.workOrderId}</Link>
    </li>)}</ul>
  </section>)}</div>
}

export function RiskOverviewPanel({ overview, clues, onFilterType, onFilterConversation, range = null, onRange = () => undefined,
  hotConversation = null, onMarker }: {
  overview: RiskOverviewView; clues: ProductClueView[]
  onFilterType: (type: string) => void; onFilterConversation: (conversationId: string) => void
  /** 框选的时间段（X-1）：三块面板与风险列表按它筛选 */
  range?: DateRange | null; onRange?: (range: DateRange | null) => void
  hotConversation?: string | null; onMarker?: (conversationId: string) => void
}) {
  const { counts } = overview
  const levelTotal = Math.max(1, Object.values(overview.levels).reduce((a, b) => a + b, 0))
  const typeRows = Object.entries(overview.types).sort((a, b) => b[1] - a[1])
  const typeMax = Math.max(1, ...typeRows.map(([, v]) => v))
  const [allDays, setAllDays] = useState(false)
  const everyDay = [...new Set(overview.hourly.map((b) => b.date))].sort()
  const dense = densestWindow(overview.hourly)
  const days = range ? daysIn(everyDay, range) : allDays ? everyDay : dense
  const pick = (date: string) => {
    const shown = windowFrom(overview.hourly, date)
    if (shown.length) onRange({ from: shown[0], to: shown.at(-1)! })
  }
  // 标题数字随当前显示的日期
  const shownBuckets = overview.hourly.filter((b) => days.includes(b.date))
  const shownTotal = shownBuckets.reduce((sum, b) => sum + b.calm + b.dissatisfied + b.angry, 0)
  const shownNegative = shownBuckets.reduce((sum, b) => sum + b.dissatisfied + b.angry, 0)
  const md = (d?: string) => d?.slice(5).replace('-', '/')
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
          <span className="yt-num">{days.length ? `${md(days[0])}–${md(days.at(-1))}` : '—'}</span>
          <span>消费者消息 <b>{shownTotal}</b> 负面 <b>{shownTotal ? Math.round((shownNegative / shownTotal) * 100) : 0}%</b></span>
          {range && <button type="button" className="yt-dist-clear" aria-label="清除时间段" onClick={() => onRange(null)}>
            {md(range.from)}–{md(range.to)} ×</button>}
          {dense.length < everyDay.length && <span className="yt-dist-range" role="group" aria-label="声纹范围">
            <button type="button" aria-pressed={!allDays && !range} onClick={() => { setAllDays(false); onRange(null) }}>密集 7 天</button>
            <button type="button" aria-pressed={allDays && !range} onClick={() => { setAllDays(true); onRange(null) }}>全部 {everyDay.length} 天</button>
          </span>}
          <span className="yt-legend"><i className="is-fury" />激烈<i className="is-upset" />不满<i className="is-calm" />平稳<i className="is-marker" />高风险会话</span>
        </div>
        <DistributionVoiceprint overview={overview} days={days} hot={hotConversation}
          onMarker={onMarker ?? onFilterConversation} onBrush={onRange} />
        {(range || !allDays) && dense.length < everyDay.length && <DistOverview overview={overview} shown={days} onPick={pick}
          onShift={(n) => onRange(shiftRange(everyDay, range ?? { from: days[0], to: days.at(-1)! }, n))} />}
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
        {!clues.length && <p className="yt-clues-empty">{range ? '该时段无商品线索' : '暂无商品线索'}</p>}
        <ul className="yt-clues">{clues.slice(0, 4).map((clue) => <li key={clue.productName}>
          <Popover trigger="click" placement="bottomLeft" title={clue.productName} destroyOnHidden
            content={<ClueCases clue={clue} onFilterConversation={onFilterConversation} />}>
            <button type="button" className="yt-clue-name" aria-label={`展开订单 ${clue.productName}`}>
              <strong title={clue.productName}>{clue.productName}</strong></button>
          </Popover>
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
