import { memo, useId } from 'react'
import type { ServiceScoreView } from '../../api/client'
import { shHourMinute } from '../service-desk/shTime'
import { nodeTags, serviceEvents, smoothPath } from './replayModel'

type Note = ServiceScoreView['notes'][number]
const LEVEL_Y = { angry: 0, dissatisfied: 1, calm: 2 } as const
const GRID = ['激烈', '不满', '平稳'] as const
const TOP = 34, GAP = 34, LEFT = 40, STEP = 30
const BASE = TOP + GAP * 2
const AXIS = BASE + 46
export const REPLAY_HEIGHT = AXIS + 44

/**
 * 对话回放图（风险页反馈 4）：上半消费者情绪平滑曲线（激烈红→平稳绿渐变填充，三条网格线），
 * 节点上方写具体标签；下半服务轴与节点虚线对齐，写 超时/AI安抚/转人工/具体动作。点节点滚到该句。
 * 图形 aria-hidden，消息列表是等价内容。
 */
export const EmotionReplay = memo(function EmotionReplay({ score, activeId, onPick }: {
  score: ServiceScoreView; activeId?: string | null; onPick?: (messageId: string) => void
}) {
  const gid = useId().replace(/:/g, '')
  const laid = score.notes.filter((n) => n.role !== 'system').map((note, i) => ({ note, x: LEFT + 12 + i * STEP }))
  const xOf = new Map(laid.map((item) => [item.note.messageId, item.x]))
  const width = Math.max(360, LEFT + 24 + laid.length * STEP)
  const yOf = (note: Note) => TOP + GAP * LEVEL_Y[note.level ?? 'calm']
  const nodes = laid.filter((item) => item.note.role === 'customer' && item.note.level).map((item) => ({ ...item, y: yOf(item.note) }))
  const line = smoothPath(nodes)
  const area = nodes.length > 1 ? `${line} L${nodes.at(-1)!.x} ${BASE} L${nodes[0].x} ${BASE} Z` : ''
  const events = serviceEvents(score, xOf)
  const labelled = laid.filter((_, i) => i === 0 || i === laid.length - 1 || i % 6 === 0)
  return <div className="yt-replay-chart" aria-hidden="true">
    <svg width={width} height={REPLAY_HEIGHT} viewBox={`0 0 ${width} ${REPLAY_HEIGHT}`}>
      <defs>
        <linearGradient id={`emo-${gid}`} x1="0" y1={TOP} x2="0" y2={BASE} gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--m-fury, #dd4a5f)" stopOpacity="0.42" />
          <stop offset="0.5" stopColor="var(--m-upset, #c98216)" stopOpacity="0.22" />
          <stop offset="1" stopColor="var(--m-calm, #23c48a)" stopOpacity="0.10" />
        </linearGradient>
        <linearGradient id={`emo-line-${gid}`} x1="0" y1={TOP} x2="0" y2={BASE} gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="var(--m-fury, #dd4a5f)" /><stop offset="0.5" stopColor="var(--m-upset, #c98216)" />
          <stop offset="1" stopColor="var(--m-calm, #23c48a)" />
        </linearGradient>
      </defs>
      {GRID.map((name, i) => <g key={name}>
        <text x={0} y={TOP + GAP * i + 4} className="yt-rc-grid-t">{name}</text>
        <line x1={LEFT} x2={width} y1={TOP + GAP * i} y2={TOP + GAP * i} className="yt-rc-grid" />
      </g>)}
      {area && <path d={area} fill={`url(#emo-${gid})`} className="yt-rc-area" />}
      {line && <path d={line} fill="none" stroke={`url(#emo-line-${gid})`} className="yt-rc-line" />}
      {events.filter((e) => e.label).map((e) => <line key={`g-${e.messageId}`} x1={e.x} x2={e.x} y1={TOP - 6} y2={AXIS - 6}
        className="yt-rc-guide" />)}
      <text x={0} y={AXIS + 4} className="yt-rc-grid-t">服务</text>
      <line x1={LEFT} x2={width} y1={AXIS} y2={AXIS} className="yt-rc-axis" />
      {events.map((e, i) => <g key={e.messageId} className={`yt-rc-ev is-${e.tone}`}>
        <circle cx={e.x} cy={AXIS} r={e.label ? 4 : 2.5} onClick={() => onPick?.(e.messageId.replace(/:wait$/, ''))} />
        {e.label && <text x={e.x} y={AXIS + 18 + (i % 2) * 13} textAnchor="middle">{e.label}</text>}
      </g>)}
      {nodes.map(({ note, x, y }) => {
        const tags = nodeTags(note)
        const on = note.messageId === activeId
        return <g key={note.messageId} className={`yt-rc-node is-${note.level}${on ? ' is-on' : ''}`} onClick={() => onPick?.(note.messageId)}>
          <circle cx={x} cy={y} r={on ? 6.5 : 4.5} />
          {tags.length > 0 && <text x={x} y={y - 11} textAnchor="middle" className="yt-rc-tag">
            {tags.map((t) => `[${t}]`).join('')}</text>}
        </g>
      })}
      {labelled.map(({ note, x }) => <text key={`t-${note.messageId}`} x={x} y={REPLAY_HEIGHT - 2} textAnchor="middle" className="yt-rc-time">
        {shHourMinute(note.at)}</text>)}
    </svg>
  </div>
})
