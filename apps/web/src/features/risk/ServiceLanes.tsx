import { Tooltip } from 'antd'
import type { ConsumerProfileView, RiskIncidentDetailView } from '../../api/client'
import { EmotionSwatch } from '../voiceprint/EmotionSwatch'
import { buildLanes, daySegments, xPercent } from './serviceLanes'

const DAY = 86400000
const md = (day: number) => {
  const d = new Date(day * DAY)
  return `${String(d.getUTCMonth() + 1).padStart(2, '0')}/${String(d.getUTCDate()).padStart(2, '0')}`
}

/** 服务轨迹：按天的多源泳道（进线 / 订单 / 工单 / 承诺 / 处置），不画情绪曲线。 */
export function ServiceLanes({ detail, profile, onContact }: {
  detail: RiskIncidentDetailView
  profile: ConsumerProfileView | null
  onContact: (conversationId: string) => void
}) {
  const lanes = buildLanes(detail, profile)
  if (!lanes.length) return <p className="yt-empty">暂无服务轨迹</p>
  const segments = daySegments(lanes)
  const step = 100 / segments.length
  return <div className="yt-lanes" role="table" aria-label="服务轨迹">
    <div className="yt-lanes-axis" role="row">
      <span role="columnheader" />
      <div className="yt-lanes-track">{segments.map((seg, i) => <span key={seg.day} className="yt-lanes-day" style={{ left: `${i * step}%`, width: `${step}%` }}>
        {seg.gapBefore && <i className="yt-lanes-gap">//</i>}{md(seg.day)}</span>)}</div>
    </div>
    {lanes.map((lane) => <div key={lane.key} className={`yt-lanes-row is-${lane.key}`} role="row">
      <span className="yt-lanes-name" role="rowheader">{lane.label}</span>
      <div className="yt-lanes-track" role="cell">
        {lane.nodes.map((node) => {
          const left = xPercent(node.at, segments)
          const right = node.end != null ? xPercent(node.end, segments) : null
          const tone = node.tone ? ` is-${node.tone}` : ''
          if (lane.key === 'contacts') return <Tooltip key={node.key} title={node.title}>
            <button type="button" className="yt-lanes-contact" style={{ left: `${left}%` }} aria-label={`进线 ${node.label}`}
              onClick={() => node.conversationId && onContact(node.conversationId)}>
              <EmotionSwatch size="sm" bands={node.levels ?? []} /></button></Tooltip>
          if (right != null && right > left) return <Tooltip key={node.key} title={node.title}>
            <span className={`yt-lanes-bar${node.open ? ' is-open' : ''}${tone}`} style={{ left: `${left}%`, width: `${right - left}%` }} tabIndex={0}>
              <em>{node.label}</em></span></Tooltip>
          return <Tooltip key={node.key} title={node.title}>
            <span className={`yt-lanes-dot${tone}`} style={{ left: `${left}%` }} tabIndex={0}><i /><em>{node.label}</em></span></Tooltip>
        })}
      </div>
    </div>)}
  </div>
}
