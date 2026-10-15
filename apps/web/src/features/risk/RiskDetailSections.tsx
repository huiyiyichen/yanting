import { ClockCircleOutlined, FileTextOutlined, MessageOutlined, ShoppingOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'
import type { ConsumerProfileView, RiskIncidentDetailView } from '../../api/client'
import { HighlightedText } from '../service-desk/HighlightedText'

type Emotion = NonNullable<RiskIncidentDetailView['emotionHistory']>[number]
type Evidence = RiskIncidentDetailView['evidence'][number]
const LEVEL = { angry: 0, dissatisfied: 1, calm: 2 } as const
const EMO_LABEL = { angry: '激烈', dissatisfied: '不满', calm: '平稳' } as const
const time = (value?: string | null) => {
  const match = value?.match(/(\d{2}):(\d{2})/)
  return match ? `${match[1]}:${match[2]}` : ''
}
const day = (value?: string | null) => value?.slice(5, 10).replace('-', '/') ?? ''
const ts = (value: string) => Date.parse(value.replace(' ', 'T')) || 0

/** 情绪轨迹：单会话内消费者每条消息的情绪，三档纵轴；升级段（升到激烈的那一跳）用色块标出，客服回复为底部金色刻度。 */
export function RiskEmotionTrack({ history, servicePoints = [] }: {
  history: Emotion[]; servicePoints?: RiskIncidentDetailView['servicePoints']
}) {
  const points = [...history].sort((a, b) => ts(a.occurredAt) - ts(b.occurredAt))
  if (!points.length) return <p className="yt-empty">暂无情绪记录</p>
  const W = 400, H = 132, L = 40, R = 392, T = 14, B = 104
  const t0 = ts(points[0].occurredAt), t1 = ts(points[points.length - 1].occurredAt)
  const span = Math.max(1, t1 - t0)
  const x = (value: string, i: number) => points.length === 1 ? (L + R) / 2
    : t1 === t0 ? L + ((R - L) * i) / (points.length - 1) : L + ((ts(value) - t0) / span) * (R - L)
  const y = (emotion: Emotion['emotion']) => T + (LEVEL[emotion] * (B - T)) / 2
  const xy = points.map((p, i) => ({ p, x: x(p.occurredAt, i), y: y(p.emotion) }))
  const jumps = xy.flatMap((pt, i) => i > 0 && pt.p.emotion === 'angry' && xy[i - 1].p.emotion !== 'angry' ? [[xy[i - 1].x, pt.x] as const] : [])
  const first = points[0].emotion, last = points[points.length - 1].emotion
  const label = `情绪轨迹：${EMO_LABEL[first]}到${EMO_LABEL[last]}，${points.length} 条消息`
  return <div className="yt-etrack">
    <svg role="img" aria-label={label} viewBox={`0 0 ${W} ${H}`} width="100%">
      {(['angry', 'dissatisfied', 'calm'] as const).map((emotion) => <g key={emotion}>
        <text x={0} y={y(emotion) + 4} className="yt-etrack-axis">{EMO_LABEL[emotion]}</text>
        <line x1={L} x2={R} y1={y(emotion)} y2={y(emotion)} className="yt-etrack-grid" />
      </g>)}
      {jumps.map(([a, b]) => <g key={a}>
        <rect x={a} y={T - 8} width={Math.max(6, b - a)} height={B - T + 16} className="yt-etrack-band" />
        <text x={(a + b) / 2} y={T - 1} textAnchor="middle" className="yt-etrack-tag">升级</text>
      </g>)}
      {servicePoints.filter((s) => ts(s.occurredAt) >= t0 && ts(s.occurredAt) <= t1).map((s) => {
        const sx = L + ((ts(s.occurredAt) - t0) / span) * (R - L)
        return <g key={s.messageId}><line x1={sx} x2={sx} y1={T} y2={B} className="yt-etrack-svc" />
          <circle cx={sx} cy={B + 2} r={2} className="yt-etrack-svc-dot" /><title>{`客服 ${time(s.occurredAt)}`}</title></g>
      })}
      <polyline points={xy.map((pt) => `${pt.x},${pt.y}`).join(' ')} className="yt-etrack-line" />
      {xy.map((pt) => <circle key={pt.p.messageId} cx={pt.x} cy={pt.y} r={4} className={`yt-etrack-dot is-${pt.p.emotion}`}>
        <title>{`${time(pt.p.occurredAt)} ${EMO_LABEL[pt.p.emotion]}：${pt.p.body}`}</title></circle>)}
      <text x={L} y={H - 4} className="yt-etrack-axis">{time(points[0].occurredAt)}</text>
      {points.length > 1 && <text x={R} y={H - 4} textAnchor="end" className="yt-etrack-axis">{time(points[points.length - 1].occurredAt)}</text>}
    </svg>
  </div>
}

export function emotionNow(history: Emotion[]) {
  const last = [...history].sort((a, b) => ts(a.occurredAt) - ts(b.occurredAt)).at(-1)
  return last ? { emotion: last.emotion, label: EMO_LABEL[last.emotion] } : null
}

export type TriggerRow = { key: string; type: string; high: boolean; quotes: Evidence[]; summary: string; tools?: ReactNode }

/** 触发依据：左列风险类型，右列原话气泡（时间、触发词下划线）；同一类型连续多条合并到一个气泡，按时间段标注。 */
export function RiskTriggers({ rows, onOpen }: { rows: TriggerRow[]; onOpen: (conversationId: string) => void }) {
  return <div className="yt-ev">
    {rows.map((row) => {
      const messages = row.quotes.filter((q) => q.kind.includes('message') || q.kind === 'history_context')
        .sort((a, b) => ts(a.occurredAt ?? '') - ts(b.occurredAt ?? ''))
      const others = row.quotes.filter((q) => !messages.includes(q))
      const range = messages.length > 1 && time(messages[0].occurredAt) !== time(messages.at(-1)!.occurredAt)
        ? `${time(messages[0].occurredAt)} → ${time(messages.at(-1)!.occurredAt)}` : time(messages[0]?.occurredAt)
      const cid = messages.find((m) => m.conversationId)?.conversationId
      return <div className="yt-ev-item" key={row.key}>
        <div className={`yt-ev-type${row.high ? ' hi' : ''}`}>{row.type}{row.tools}</div>
        <div className="yt-ev-quotes">
          {messages.length > 0 && <div className="yt-ev-quote">
            <small>{day(messages[0].occurredAt)} {range}
              {cid && <button type="button" className="yt-ev-open" aria-label={`打开会话 ${cid}`} onClick={() => onOpen(cid)}><MessageOutlined /></button>}
            </small>
            {messages.map((m) => <p key={m.ref}><HighlightedText text={m.body} highlights={m.highlights} /></p>)}
          </div>}
          {others.length > 0 && <div className="yt-ev-quote"><small>{others.map((q) => q.label).join('、')}</small><p>{row.summary}</p></div>}
          {!row.quotes.length && <div className="yt-ev-quote"><p>{row.summary}</p></div>}
        </div>
      </div>
    })}
  </div>
}

type LinkRow = { key: string; kind: 'promise' | 'order' | 'ticket'; title: string; sub: string; state: string; onClick?: () => void }
const ICON = { promise: <ClockCircleOutlined />, order: <ShoppingOutlined />, ticket: <FileTextOutlined /> }

export function linkedRecords(detail: RiskIncidentDetailView, profile: ConsumerProfileView | null,
  openTicket: (ticketId: string) => void): LinkRow[] {
  const promises: LinkRow[] = (profile?.promises ?? []).filter((p) => p.status !== 'fulfilled').map((p) => ({
    key: `p-${p.sourceRef}`, kind: 'promise', title: `${day(p.madeAt)} 承诺：${p.text}`,
    sub: p.sourceRef.split(':')[1] ?? '', state: p.status === 'due' ? `已到期 ${day(p.dueAt)}` : `截至 ${day(p.dueAt)}`,
  }))
  const orders: LinkRow[] = detail.contexts.flatMap((c) => c.orders).filter((o, i, all) =>
    all.findIndex((x) => x.orderId === o.orderId) === i).map((o) => ({
    key: `o-${o.orderId}`, kind: 'order', title: o.productName || o.sku || '订单',
    sub: [o.orderId, o.paidAmountMinor != null ? `¥${(o.paidAmountMinor / 100).toFixed(2)}` : '', o.carrier ?? ''].filter(Boolean).join('　'),
    state: o.shippedAt ? '已发货' : o.sourceStatus ?? '',
  }))
  const tickets: LinkRow[] = detail.tickets.map((t) => ({
    key: `t-${t.ticketId}`, kind: 'ticket', title: t.title, sub: [t.ticketId, t.assignee].filter(Boolean).join('　'),
    state: ({ pending: '待处理', in_progress: '处理中', waiting_customer: '待客户', waiting_internal: '待内部', resolved: '已完成' } as Record<string, string>)[t.status] ?? t.status,
    onClick: () => openTicket(t.ticketId),
  }))
  return [...promises, ...orders, ...tickets]
}

/** 关联记录：未兑现承诺（金色置顶）→ 订单 → 工单。 */
export function RiskLinks({ rows }: { rows: LinkRow[] }) {
  if (!rows.length) return <p className="yt-empty">暂无关联记录</p>
  return <div className="yt-links">
    {rows.map((row) => {
      const body = <><span className="ic">{ICON[row.kind]}</span>
        <span className="yt-link-main"><b>{row.title}</b>{row.sub && <span className="n">{row.sub}</span>}</span>
        <span className="st">{row.state}</span></>
      return row.onClick
        ? <button type="button" key={row.key} className={`yt-link is-${row.kind}`} onClick={row.onClick}>{body}</button>
        : <div key={row.key} className={`yt-link is-${row.kind}`}>{body}</div>
    })}
  </div>
}
