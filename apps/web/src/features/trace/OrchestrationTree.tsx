import { ApiOutlined, CheckCircleFilled, ClockCircleOutlined, CloseCircleFilled, MinusCircleOutlined, RightOutlined, RobotOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import type { CSSProperties } from 'react'
import { useMemo } from 'react'
import { buildOrchestration, cardStateText, fmtMs, type OrchCard, type TraceSpan } from './traceModel'

const ICON: Record<string, typeof RobotOutlined> = { safety_gate: SafetyCertificateOutlined, output_gate: SafetyCertificateOutlined, send_gate: SafetyCertificateOutlined, program_check: ApiOutlined }
const STATE_ICON = { ok: CheckCircleFilled, fail: CloseCircleFilled, skipped: MinusCircleOutlined, none: MinusCircleOutlined, running: ClockCircleOutlined }

function Card({ card, total, selected, lit, compact, onSelect }: {
  card: OrchCard; total: number; selected: boolean; lit: Set<string> | null; compact: boolean; onSelect: (spanId: string) => void
}) {
  const Icon = ICON[card.key] ?? RobotOutlined
  const StateIcon = STATE_ICON[card.state]
  const dim = lit != null && (!card.spanId || !lit.has(card.spanId))
  const left = Math.min(100, (card.start / total) * 100)
  const width = card.durationMs ? Math.max(2, Math.min(100 - left, ((card.durationMs ?? 0) / total) * 100)) : 0
  return <button type="button" className={`yt-oc is-${card.state}${card.state === 'ok' && card.issues ? ' has-issues' : ''}${selected ? ' is-sel' : ''}${dim ? ' is-dim' : ''}`}
    disabled={!card.spanId} onClick={() => card.spanId && onSelect(card.spanId)} aria-label={card.label}>
    <span className="yt-oc-head">
      <span className="ic"><Icon /></span>
      <span className="nm"><b>{card.label}</b><small><span className="rl">{card.role.split(' · ')[0]} · </span><StateIcon className="st" /> {cardStateText(card)}</small></span>
      {card.durationMs != null && <span className="dur yt-num">{fmtMs(card.durationMs)}</span>}
    </span>
    <span className="yt-oc-sum" title={card.summary}>{card.summary}</span>
    {!compact && width > 0 && <span className="yt-oc-bar" aria-hidden><i style={{ left: `${left}%`, width: `${width}%` }} /></span>}
    <span className="yt-oc-foot">
      {card.model ? <span className="md" title={card.model}>{card.model}</span> : <span className="md is-none">{card.state === 'none' ? '—' : '无模型调用'}</span>}
      {card.spanId && <span className="n">{card.records} 条<RightOutlined /></span>}
    </span>
  </button>
}

/** 编排卡片树（反馈 10-18 #3）：Leader/闸门居中，并行 Worker 分叉再汇合；卡片内含状态、产出、耗时、模型。 */
export function OrchestrationTree({ startedAt, spans, selected, lit = null, compact = false, onSelect }: {
  startedAt: string; spans: TraceSpan[]; selected?: string | null; lit?: Set<string> | null; compact?: boolean
  onSelect: (spanId: string) => void
}) {
  const { rows, total } = useMemo(() => buildOrchestration(startedAt, spans), [startedAt, spans])
  const cards = rows.flatMap((r) => r.cards).filter((c) => c.durationMs != null)
  return <div className={`yt-orch${compact ? ' is-compact' : ''}`} aria-label="编排流程">
    <div className="yt-orch-over" aria-label="整体时间轴">
      <span className="lbl">总耗时 <b className="yt-num">{fmtMs(total)}</b></span>
      <span className="track">{cards.map((c) => <i key={c.key} className={`is-${c.state}`} title={`${c.label} ${fmtMs(c.durationMs)}`}
        style={{ left: `${(c.start / total) * 100}%`, width: `${Math.max(0.8, ((c.durationMs ?? 0) / total) * 100)}%` } as CSSProperties} />)}</span>
    </div>
    {rows.map((row, i) => <div key={row.key} className={`yt-orch-row${row.fan ? ' is-fan' : ''}${i === 0 ? ' is-first' : ''}`}
      style={{ '--n': row.cards.length } as CSSProperties}>
      {row.fan && row.title && <span className="yt-orch-tag">{row.title}</span>}
      <div className="yt-orch-cards">
        {row.cards.map((card) => <Card key={card.key} card={card} total={total} compact={compact}
          selected={Boolean(card.spanId && card.spanId === selected)} lit={lit} onSelect={onSelect} />)}
      </div>
    </div>)}
  </div>
}
