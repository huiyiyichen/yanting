import type { ConsumerProfileView, ConsumerServiceContextView } from '../../api/client'

type Node = { key: string; at: string; kind: string; tone: 'order' | 'ticket' | 'promise' | 'contact' | 'fury' | 'due'; title: string; state?: string }
const ts = (v?: string | null) => (v ? Date.parse(v.replace(' ', 'T')) || 0 : 0)
const md = (v?: string | null) => v?.slice(5, 10).replace('-', '/') ?? ''
const hm = (v?: string | null) => v?.match(/[T ](\d{2}:\d{2})/)?.[1] ?? ''
const tail = (id: string) => (id.length > 8 ? `…${id.slice(-4)}` : id)
const LEVEL: Record<string, number> = { angry: 0, dissatisfied: 1, calm: 2 }
const LEVEL_LABEL: Record<string, string> = { angry: '激烈', dissatisfied: '不满', calm: '平稳' }

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
function EmotionCurve({ trail }: { trail: ConsumerProfileView['emotionTrail'] }) {
  const pts = trail.filter((p) => p.role === 'customer' && p.level && p.level in LEVEL)
  if (pts.length < 2) return null
  const W = 360, H = 64, L = 30, R = 352, T = 8, B = 52
  const x = (i: number) => L + (i * (R - L)) / (pts.length - 1)
  const y = (lv: string) => T + (LEVEL[lv] * (B - T)) / 2
  const first = pts[0].level!, last = pts[pts.length - 1].level!
  return <svg className="yt-jcurve" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`本次情绪：${LEVEL_LABEL[first]}到${LEVEL_LABEL[last]}`}>
    {Object.keys(LEVEL).map((lv) => <g key={lv}><text x={0} y={y(lv) + 4}>{LEVEL_LABEL[lv]}</text>
      <line x1={L} x2={R} y1={y(lv)} y2={y(lv)} /></g>)}
    <polyline points={pts.map((p, i) => `${x(i)},${y(p.level!)}`).join(' ')} />
    {pts.map((p, i) => <circle key={p.sourceRef} cx={x(i)} cy={y(p.level!)} r={3.5} className={`is-${p.level}`}><title>{`${hm(p.at)} ${LEVEL_LABEL[p.level!]}`}</title></circle>)}
  </svg>
}

export function ServiceJourney({ context, profile }: { context: ConsumerServiceContextView | null; profile: ConsumerProfileView | null }) {
  const nodes = journeyNodes(context, profile)
  const history = context?.historyServices ?? []
  const contacts = [...history.map((h) => ({ id: h.conversationId, at: h.lastAt ?? h.firstAt ?? '', same: h.relation === 'same_order', current: false })),
    ...(context ? [{ id: context.conversationId, at: currentStart(context), same: false, current: true }] : [])].sort((a, b) => ts(a.at) - ts(b.at))
  const t0 = ts(contacts[0]?.at), t1 = ts(contacts.at(-1)?.at)
  const sameOrder = history.filter((h) => h.relation === 'same_order').length
  const own = profile?.conversationId === context?.conversationId ? profile : null
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
    {own && own.emotionTrail.length > 1 && <section className="service-section yt-card" aria-label="本次情绪">
      <h3>本次情绪{own.escalatedAt && <span className="r is-fury">{hm(own.escalatedAt)} 升级</span>}</h3>
      <EmotionCurve trail={own.emotionTrail} />
    </section>}
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
