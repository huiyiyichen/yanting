import { ApiOutlined, CheckCircleFilled, CheckOutlined, ClockCircleOutlined, CloseCircleFilled, CloseOutlined, CustomerServiceOutlined, MinusCircleOutlined, RightOutlined, RobotOutlined, SafetyCertificateOutlined, SendOutlined, UserOutlined } from '@ant-design/icons'
import type { CSSProperties } from 'react'
import { useMemo } from 'react'
import { buildOrchestration, cardStateText, fmtMs, type OrchCard, type TraceSpan } from './traceModel'

const ICON: Record<string, typeof RobotOutlined> = { safety_gate: SafetyCertificateOutlined, output_gate: SafetyCertificateOutlined, send_gate: SendOutlined, program_check: ApiOutlined }
const STATE_ICON = { ok: CheckCircleFilled, fail: CloseCircleFilled, skipped: MinusCircleOutlined, none: MinusCircleOutlined, running: ClockCircleOutlined }
const BADGE: Record<OrchCard['badge'], string> = { leader: 'Leader', worker: 'Worker', gate: '闸门', check: '核验', agent: 'Agent' }

function Card({ card, total, selected, lit, compact, onSelect }: {
  card: OrchCard; total: number; selected: boolean; lit: Set<string> | null; compact: boolean; onSelect: (spanId: string) => void
}) {
  const Icon = ICON[card.key] ?? RobotOutlined
  const StateIcon = STATE_ICON[card.state]
  const dim = lit != null && (!card.spanId || !lit.has(card.spanId))
  const left = Math.min(100, (card.start / total) * 100)
  const width = card.durationMs ? Math.max(2, Math.min(100 - left, ((card.durationMs ?? 0) / total) * 100)) : 0
  const hits = card.checks.filter((c) => c.hit).length
  return <button type="button" className={`yt-oc is-${card.state} is-${card.badge}${(card.state === 'ok' && card.issues) || hits ? ' has-issues' : ''}${selected ? ' is-sel' : ''}${dim ? ' is-dim' : ''}`}
    disabled={!card.spanId} onClick={() => card.spanId && onSelect(card.spanId)} aria-label={card.label}>
    <span className="yt-oc-head">
      <span className="ic"><Icon /></span>
      <span className="nm"><b>{card.label}<em className={`bd is-${card.badge}`}>{BADGE[card.badge]}</em></b>
        <small><StateIcon className="st" /> {cardStateText(card)}</small></span>
      {card.durationMs != null && <span className="dur yt-num">{fmtMs(card.durationMs)}</span>}
    </span>
    {card.inputs.length > 0 && <span className="yt-oc-in" aria-label="收到">
      {card.inputs.map((i) => <span key={i.label}><b>{i.label}</b>{i.text}</span>)}</span>}
    <span className="yt-oc-sum" title={card.summary}>{card.summary}</span>
    {card.checks.length > 0 && <span className="yt-oc-checks" aria-label="检查项">
      {card.checks.slice(0, compact ? 3 : 6).map((c) => <span key={c.name} className={c.hit ? 'is-hit' : undefined}>
        {c.hit ? <CloseOutlined /> : <CheckOutlined />}<b>{c.name}</b>{!compact && <i>{c.detail}</i>}</span>)}
    </span>}
    {!compact && width > 0 && <span className="yt-oc-bar" aria-hidden><i style={{ left: `${left}%`, width: `${width}%` }} /></span>}
    <span className="yt-oc-foot">
      {card.model ? <span className="md" title={card.model}>{card.model}</span> : <span className="md is-none">{card.badge === 'gate' || card.badge === 'check' ? '规则判断' : '无模型调用'}</span>}
      {card.spanId && <span className="n">{card.records} 条<RightOutlined /></span>}
    </span>
  </button>
}

/**
 * 编排卡片树（反馈 10-18 #3、10-19 #1/#2）：从客户这句话开始，经闸门、Leader 派发的并行 Worker、
 * 汇合起草、两道核验，到最终发出（或转人工）的那句话结束。没经过的节点不显示。
 */
export function OrchestrationTree({ startedAt, spans, selected, lit = null, compact = false, onSelect, trigger, outcome, outcomeStatus }: {
  startedAt: string; spans: TraceSpan[]; selected?: string | null; lit?: Set<string> | null; compact?: boolean
  onSelect: (spanId: string) => void
  trigger?: string | null; outcome?: string | null; outcomeStatus?: string
}) {
  const { rows, total } = useMemo(() => buildOrchestration(startedAt, spans), [startedAt, spans])
  const cards = rows.flatMap((r) => r.cards).filter((c) => c.durationMs != null)
  const handoff = outcomeStatus === 'handoff' || outcomeStatus === 'failed'
  return <div className={`yt-orch${compact ? ' is-compact' : ''}`} aria-label="编排流程">
    <div className="yt-orch-over" aria-label="整体时间轴">
      <span className="lbl">总耗时 <b className="yt-num">{fmtMs(total)}</b></span>
      <span className="track">{cards.map((c) => <i key={c.key} className={`is-${c.state}`} title={`${c.label} ${fmtMs(c.durationMs)}`}
        style={{ left: `${(c.start / total) * 100}%`, width: `${Math.max(0.8, ((c.durationMs ?? 0) / total) * 100)}%` } as CSSProperties} />)}</span>
    </div>
    {trigger != null && <div className="yt-orch-end is-in"><span className="who"><UserOutlined />客户消息</span><q>{trigger || '（图片或空消息）'}</q></div>}
    {rows.map((row, i) => <div key={row.key} className={`yt-orch-row${row.fan ? ' is-fan' : ''}${i === 0 && trigger == null ? ' is-first' : ''}`}
      style={{ '--n': row.cards.length } as CSSProperties}>
      {row.title && <span className="yt-orch-tag">{row.title}</span>}
      <div className="yt-orch-cards">
        {row.cards.map((card) => <Card key={card.key} card={card} total={total} compact={compact}
          selected={Boolean(card.spanId && card.spanId === selected)} lit={lit} onSelect={onSelect} />)}
      </div>
    </div>)}
    {(outcome != null || handoff) && <div className={`yt-orch-row is-tail`}><div className={`yt-orch-end is-out${handoff ? ' is-handoff' : ''}`}>
      <span className="who">{handoff ? <><CustomerServiceOutlined />转人工</> : <><RobotOutlined />发给客户</>}</span>
      {outcome ? <q>{outcome}</q> : <q className="none">{handoff ? '没有自动发送，交给客服继续处理' : '—'}</q>}
    </div></div>}
  </div>
}
