import { Tooltip } from 'antd'
import { Link } from 'react-router-dom'
import type { ConsumerProfileView, RiskIncidentDetailView } from '../../api/client'
import { EmotionSwatch } from '../voiceprint/EmotionSwatch'
import { buildMilestones, orderStages } from './serviceTrackModel'

const fmt = (ms: number) => {
  const d = new Date(ms + 8 * 3600000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getUTCMonth() + 1)}/${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`
}
const PROMISE = { overdue: '已超期', pending: '未兑现', fulfilled: '已兑现' } as const

/** 服务轨迹（风险页反馈 5）：顶部订单主干进度条，下方里程碑卡片（进线、承诺、工单、处置）。 */
export function ServiceTrack({ detail, profile, onContact }: {
  detail: RiskIncidentDetailView; profile: ConsumerProfileView | null; onContact: (conversationId: string) => void
}) {
  const stages = orderStages(detail)
  const items = buildMilestones(detail, profile)
  if (!items.length && !stages.some((s) => s.done)) return <p className="yt-empty">暂无服务轨迹</p>
  const reached = stages.filter((s) => s.done).length
  return <div className="yt-track" aria-label="服务轨迹">
    <ol className="yt-track-spine" aria-label="订单进度">
      {stages.map((s, i) => <li key={s.key} className={`${s.done ? 'is-done' : ''}${i === reached - 1 ? ' is-now' : ''}`}>
        <i /><b>{s.label}</b>{s.at != null && <span className="yt-num">{fmt(s.at)}</span>}
      </li>)}
    </ol>
    <ol className="yt-track-cards">
      {items.map((m) => <li key={m.key} className={`yt-track-card is-${m.kind}`}>
        <span className="t yt-num">{fmt(m.at)}</span>
        {m.kind === 'contact' && <Tooltip title={m.previous ? <span className="yt-track-prev">{m.previous}</span> : undefined}>
          <button type="button" onClick={() => onContact(m.conversationId)} aria-label={`第${m.nth}次进线 ${m.conversationId}`}>
            <b>第 {m.nth} 次进线</b><EmotionSwatch size="sm" bands={m.levels} /></button></Tooltip>}
        {m.kind === 'promise' && <><b>承诺</b><p>{m.text}</p><em className={`is-${m.status}`}>{PROMISE[m.status]}</em></>}
        {m.kind === 'ticket' && <><b>生成工单</b>
          <Link to={`/platform/work-orders?q=${encodeURIComponent(m.id)}`}>#{m.id}</Link>
          <p>{m.type}</p><em className={m.done ? 'is-fulfilled' : 'is-pending'}>{m.status || (m.done ? '已完结' : '处理中')}</em></>}
        {m.kind === 'handling' && <><b>{m.action}</b>{m.note && <p>{m.note}</p>}</>}
      </li>)}
    </ol>
  </div>
}
