import { shHourMinute, shMonthDay, shTimestamp } from './shTime'
import type { ConsumerProfileView, ConsumerServiceContextView } from '../../api/client'

type Node = { key: string; at: string; kind: string; tone: 'order' | 'ticket' | 'promise' | 'contact' | 'fury' | 'due'; title: string; state?: string }
const ts = shTimestamp
const md = shMonthDay
const hm = shHourMinute
const tail = (id: string) => (id.length > 8 ? `…${id.slice(-4)}` : id)

/** 本次进线时间取会话第一条消息；firstAt 可能被订单时间带早。 */
function currentStart(context: ConsumerServiceContextView | null) {
  return (context?.timeline ?? []).filter((e) => e.message).map((e) => e.occurredAt).sort((a, b) => ts(a) - ts(b))[0] ?? context?.firstAt ?? ''
}

/** 把订单、工单、承诺、进线、情绪升级合成一条业务时间线；不含聊天原文（原文在左侧会话里）。 */
export function journeyNodes(context: ConsumerServiceContextView | null, profile: ConsumerProfileView | null, now = Date.now()): Node[] {
  const nodes: Node[] = (context?.serviceNodes ?? []).map((n, i) => ({
    key: `n${i}-${n.sourceRecordId}`, at: n.occurredAt, kind: n.kind,
    tone: n.kind.startsWith('工单') ? 'ticket' : n.kind === '历史进线' ? 'contact' : 'order',
    title: n.kind === '历史进线' ? n.title : tail(n.title), state: n.status ?? undefined,
  }))
  const startedAt = currentStart(context)
  if (startedAt && context) nodes.push({ key: 'current', at: startedAt, kind: '本次进线', tone: 'contact', title: context.conversationId })
  if (profile?.conversationId === context?.conversationId && profile) {
    if (profile.escalatedAt) nodes.push({ key: 'esc', at: profile.escalatedAt, kind: '情绪升级', tone: 'fury', title: '升至激烈' })
    for (const p of profile.promises) {
      nodes.push({ key: `pm-${p.sourceRef}`, at: p.madeAt, kind: '客服承诺', tone: 'promise', title: p.text })
      if (p.status !== 'fulfilled') nodes.push({ key: `pd-${p.sourceRef}`, at: p.dueAt, kind: '承诺到期', tone: 'due',
        title: p.text, state: ts(p.dueAt) < now || p.status === 'due' ? '已到期' : '待兑现' })
    }
  }
  return nodes.sort((a, b) => ts(a.at) - ts(b.at))
}

/** 本次会话情绪曲线：消费者每条消息一个点，三档。 */

export function ServiceJourney({ context, profile }: { context: ConsumerServiceContextView | null; profile: ConsumerProfileView | null }) {
  const nodes = journeyNodes(context, profile)
  const history = context?.historyServices ?? []
  const contacts = [...history.map((h) => ({ id: h.conversationId, at: h.lastAt ?? h.firstAt ?? '', same: h.relation === 'same_order', current: false })),
    ...(context ? [{ id: context.conversationId, at: currentStart(context), same: false, current: true }] : [])].sort((a, b) => ts(a.at) - ts(b.at))
  const t0 = ts(contacts[0]?.at), t1 = ts(contacts.at(-1)?.at)
  const sameOrder = history.filter((h) => h.relation === 'same_order').length
  if (!context) return <p className="yt-empty">暂无服务记录</p>
  let lastDay = ''
  return <div className="yt-journey">
    <section className="service-section yt-card" aria-label="进线记录">
      <h3>进线<span className="r">共 {contacts.length} 次{sameOrder ? ` · 同订单 ${sameOrder} 次` : ''}</span></h3>
      {contacts.length > 1 && <div className="yt-jcontacts">
        <i className="axis" />
        {contacts.map((c) => <span key={c.id} title={`${c.id} · ${md(c.at)}`}
          className={`dot${c.current ? ' is-current' : ''}${c.same ? ' is-same' : ''}`}
          style={{ left: `${t1 === t0 ? 50 : 4 + ((ts(c.at) - t0) / (t1 - t0)) * 92}%` }} />)}
        <small className="from">{md(contacts[0].at)}</small><small className="to">{md(contacts.at(-1)!.at)}</small>
      </div>}
    </section>
    <section className="service-section yt-card" aria-label="业务节点">
      <h3>业务节点<span className="r">{nodes.length}</span></h3>
      {nodes.length ? <ol className="yt-jnodes">
        {nodes.map((n) => {
          const d = md(n.at)
          const head = d !== lastDay ? d : ''
          lastDay = d
          return <li key={n.key} className={`is-${n.tone}`}>
            <span className="d">{head}</span>
            <span className="t">{hm(n.at)}</span>
            <i className="pin" aria-hidden />
            <span className="body"><b>{n.kind}</b><span className="ttl">{n.title}</span></span>
            {n.state && <span className="st">{n.state}</span>}
          </li>
        })}
      </ol> : <p className="yt-empty">暂无业务节点</p>}
    </section>
  </div>
}
