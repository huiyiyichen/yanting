import { ApiOutlined, CheckCircleFilled, CheckOutlined, ClockCircleOutlined, CloseCircleFilled, CloseOutlined, CustomerServiceOutlined, HeartOutlined, MinusCircleOutlined, RollbackOutlined, RightOutlined, RobotOutlined, SafetyCertificateOutlined, SendOutlined, UserOutlined } from '@ant-design/icons'
import type { CSSProperties } from 'react'
import { useMemo } from 'react'
import { buildFork, buildOrchestration, cardStateText, fmtMs, type OrchCard, type OrchRow, type TraceSpan } from './traceModel'

const ICON: Record<string, typeof RobotOutlined> = {
  understand: HeartOutlined, safety_gate: SafetyCertificateOutlined, output_gate: SafetyCertificateOutlined, send_gate: SendOutlined,
  program_check: ApiOutlined, send: SendOutlined, handoff: CustomerServiceOutlined,
}
const STATE_ICON = { ok: CheckCircleFilled, fail: CloseCircleFilled, skipped: MinusCircleOutlined, none: MinusCircleOutlined, running: ClockCircleOutlined }
const BADGE: Record<OrchCard['badge'], string> = { leader: 'Leader', worker: 'Worker', gate: '闸门', check: '核验', agent: 'Agent', send: 'AI 发送', human: '人工' }

/** 连线颜色跟着目标节点的角色走：Leader 紫、Worker 蓝、核验金、闸门绿、AI 发送绿、人工橙。 */
type Tone = 'leader' | 'worker' | 'check' | 'gate' | 'send' | 'human'
const toneOf = (c: OrchCard): Tone => (c.badge === 'agent' ? 'gate' : c.badge)
const rowTone = (r: OrchRow): Tone => toneOf(r.cards[0])

/**
 * 节点之间的连线（SVG）：line=单线，out=一分多（派发），in=多合一（汇合）。
 * 走过的分支画成流动的彩色虚线，没走的分支是静止的灰色虚线。
 */
function Link({ mode, tones, on, height }: { mode: 'line' | 'out' | 'in'; tones: Tone[]; on: boolean[]; height: number }) {
  const n = tones.length
  const xs = tones.map((_, i) => ((2 * i + 1) * 50) / n)
  const mid = height / 2
  const d = (x: number) => (mode === 'line' ? `M50 0 V${height}` : mode === 'out' ? `M50 0 V${mid} H${x} V${height}` : `M${x} 0 V${mid} H50 V${height}`)
  const ends = mode === 'in' ? [50] : mode === 'line' ? [50] : xs
  return <div className="yt-link" style={{ height }} aria-hidden>
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none">
      {xs.map((x, i) => <g key={i} className={`t-${tones[i]} ${on[i] ? 'is-on' : 'is-off'}`}>
        <path className="base" d={d(x)} vectorEffect="non-scaling-stroke" />
        {on[i] && <path className="flow" d={d(x)} vectorEffect="non-scaling-stroke" />}
      </g>)}
    </svg>
    {mode !== 'in' && ends.map((x, i) => {
      const idx = mode === 'line' ? 0 : i
      return <i key={i} className={`arrow t-${tones[idx]} ${on[idx] ? 'is-on' : 'is-off'}`} style={{ left: `${x}%` }} />
    })}
  </div>
}

function Card({ card, total, selected, lit, compact, onSelect }: {
  card: OrchCard; total: number; selected: boolean; lit: Set<string> | null; compact: boolean; onSelect: (spanId: string) => void
}) {
  const Icon = ICON[card.key] ?? RobotOutlined
  const StateIcon = STATE_ICON[card.state]
  const dim = lit != null && (!card.spanId || !lit.has(card.spanId))
  const left = Math.min(100, (card.start / total) * 100)
  const width = card.durationMs ? Math.max(2, Math.min(100 - left, ((card.durationMs ?? 0) / total) * 100)) : 0
  const hits = card.checks.filter((c) => c.hit).length
  const terminal = card.badge === 'send' || card.badge === 'human'
  const issue = !terminal && ((card.state === 'ok' && card.issues) || hits)
  const stateText = terminal ? (card.state === 'ok' ? (card.badge === 'send' ? '已发送' : '已转人工') : '未走这条路') : cardStateText(card)
  return <button type="button" className={`yt-oc is-${card.state} is-${card.badge} t-${toneOf(card)}${issue ? ' has-issues' : ''}${card.trigger ? ' is-trigger' : ''}${selected ? ' is-sel' : ''}${dim ? ' is-dim' : ''}`}
    disabled={!card.spanId} onClick={() => card.spanId && onSelect(card.spanId)} aria-label={card.label}>
    <span className="yt-oc-head">
      <span className="ic"><Icon /></span>
      <span className="nm"><b>{card.label}<em className={`bd is-${card.badge}`}>{BADGE[card.badge]}</em>{card.trigger && <em className="bd is-trigger">触发转人工</em>}</b>
        <small><StateIcon className="st" /> {stateText}</small></span>
      {card.durationMs != null && <span className="dur yt-num">{fmtMs(card.durationMs)}</span>}
    </span>
    {card.inputs.length > 0 && <span className={`yt-oc-in${terminal ? ' is-plain' : ''}`} aria-label="收到">
      {card.inputs.map((i) => <span key={i.label}><b>{i.label}</b>{i.text}</span>)}</span>}
    <span className="yt-oc-sum" title={card.summary}>{card.summary}</span>
    {card.checks.length > 0 && <span className="yt-oc-checks" aria-label="检查项">
      {card.checks.slice(0, compact ? 3 : 6).map((c) => <span key={c.name} className={c.hit ? 'is-hit' : undefined}>
        {c.hit ? <CloseOutlined /> : <CheckOutlined />}<b>{c.name}</b>{!compact && <i>{c.detail}</i>}</span>)}
    </span>}
    {!compact && width > 0 && <span className="yt-oc-bar" aria-hidden><i style={{ left: `${left}%`, width: `${width}%` }} /></span>}
    <span className="yt-oc-foot">
      {card.model ? <span className="md" title={card.model}>{card.model}</span>
        : <span className="md is-none">{terminal ? (card.badge === 'human' ? '客服接手' : '发给客户') : card.badge === 'gate' || card.badge === 'check' ? '规则判断' : '无模型调用'}</span>}
      {card.spanId && <span className="n">{card.records} 条<RightOutlined /></span>}
    </span>
  </button>
}

/**
 * 编排卡片树（反馈 10-18 #3、10-19、10-20）：从客户这句话开始，经闸门、Leader 派发的并行 Worker、
 * 汇合起草、两道核验，最后分叉到「AI 自动发送」或「人工接续」。连线按角色着色，走过的路径有流动效果。
 */
export function OrchestrationTree({ startedAt, spans, selected, lit = null, compact = false, onSelect, trigger, outcome, outcomeStatus }: {
  startedAt: string; spans: TraceSpan[]; selected?: string | null; lit?: Set<string> | null; compact?: boolean
  onSelect: (spanId: string) => void
  trigger?: string | null; outcome?: string | null; outcomeStatus?: string
}) {
  const { rows, total, repair, fork } = useMemo(() => {
    const built = buildOrchestration(startedAt, spans)
    return { ...built, fork: buildFork(spans, built.rows, outcomeStatus, outcome) }
  }, [startedAt, spans, outcomeStatus, outcome])
  const cards = rows.flatMap((r) => r.cards).filter((c) => c.durationMs != null)
  const active = (r: OrchRow) => lit == null || r.cards.some((c) => c.spanId && lit.has(c.spanId))
  const forkLit = lit == null || [fork.send, fork.handoff].some((c) => c.spanId && lit.has(c.spanId))
  const forkOn = [fork.path === 'send' && forkLit, fork.path === 'handoff' && forkLit]
  const cardsOf = (row: OrchRow) => row.cards.map((card) => <div key={card.key} className="yt-orch-cell">
    <Card card={card} total={total} compact={compact} selected={Boolean(card.spanId && card.spanId === selected)} lit={lit} onSelect={onSelect} />
  </div>)
  const H = compact ? { line: 22, out: 30, in: 16 } : { line: 28, out: 38, in: 20 }
  return <div className={`yt-orch${compact ? ' is-compact' : ''}`} aria-label="编排流程">
    <div className="yt-orch-over" aria-label="整体时间轴">
      <span className="lbl">总耗时 <b className="yt-num">{fmtMs(total)}</b></span>
      <span className="track">{cards.map((c) => <i key={c.key} className={`is-${c.state} t-${toneOf(c)}`} title={`${c.label} ${fmtMs(c.durationMs)}`}
        style={{ left: `${(c.start / total) * 100}%`, width: `${Math.max(0.8, ((c.durationMs ?? 0) / total) * 100)}%` } as CSSProperties} />)}</span>
    </div>
    {trigger != null && <div className="yt-orch-end is-in"><span className="who"><UserOutlined />客户消息</span><q>{trigger || '（图片或空消息）'}</q></div>}
    {rows.map((row, i) => {
      const on = active(row)
      const tones = row.fan ? row.cards.map(toneOf) : [rowTone(row)]
      const showTop = i > 0 || trigger != null
      return <div key={row.key} className={`yt-orch-row${row.fan ? ' is-fan' : ''}`} style={{ '--n': row.cards.length } as CSSProperties}>
        {showTop && <Link mode={row.fan ? 'out' : 'line'} tones={tones} on={tones.map(() => on)} height={row.fan ? H.out : H.line} />}
        {row.title && <span className="yt-orch-tag">{row.title}</span>}
        <div className="yt-orch-cards">{cardsOf(row)}</div>
        {row.fan && <Link mode="in" tones={tones} on={tones.map(() => on)} height={H.in} />}
        {row.key === 'checks' && repair && <button type="button" className="yt-orch-loop" aria-label="修复回路"
          disabled={!repair.spanId} onClick={() => repair.spanId && onSelect(repair.spanId)}>
          <RollbackOutlined className="ic" />
          <span className="t"><b>修复回路</b>{repair.from}未过 → 打回共情起草，重新起草{repair.attempts > 2 ? ` ${repair.attempts - 1} 次` : '一次'}</span>
          {repair.reason && !compact && <q title={repair.reason}>{repair.reason}</q>}
        </button>}
      </div>
    })}
    <div className={`yt-orch-row is-fan is-fork is-${fork.path}`} style={{ '--n': 2 } as CSSProperties} aria-label="结局">
      <Link mode="out" tones={['send', 'human']} on={forkOn} height={H.out} />
      <span className="yt-orch-tag">{fork.path === 'handoff' ? `转人工${fork.reason ? ` · ${fork.reason}` : ''}` : fork.path === 'send' ? '自动发送' : '结局'}</span>
      <div className="yt-orch-cards">
        {[fork.send, fork.handoff].map((card) => <div key={card.key} className="yt-orch-cell">
          <Card card={card} total={total} compact={compact} selected={Boolean(card.spanId && card.spanId === selected)} lit={lit} onSelect={onSelect} />
        </div>)}
      </div>
    </div>
  </div>
}
