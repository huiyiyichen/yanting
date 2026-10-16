import { memo } from 'react'
import type { ServiceScoreView } from '../../api/client'
import { shHourMinute } from '../service-desk/shTime'

type Note = ServiceScoreView['notes'][number]
const PITCH = { angry: 0, dissatisfied: 1, calm: 2 } as const
const COLOR = { calm: 'var(--yt-calm)', dissatisfied: 'var(--yt-upset)', angry: 'var(--yt-fury)' } as const
const STAFF_GAP = 22
const TOP = 18
const SERVICE_Y = TOP + STAFF_GAP * 2 + 46
const AXIS_Y = SERVICE_Y + 30
export const SCORE_HEIGHT = AXIS_Y + 14
const STEP = 22
const PAD = 52

/** 音符横坐标：按消息顺序等距（相邻至少 STEP），系统消息不画。 */
export function noteLayout(notes: Note[]): { note: Note; x: number }[] {
  return notes.filter((note) => note.role !== 'system').map((note, i) => ({ note, x: PAD + i * STEP }))
}

const minutes = (ms: number) => (ms >= 60000 ? `${Math.round(ms / 60000)}′` : `${Math.round(ms / 1000)}″`)

/**
 * 服务乐谱（全景方案 2.2）：上行消费者（情绪=音高），下行服务方（人工实心、AI 空心），
 * 休止=等待（超 120 秒标时长），渐强/渐弱=相邻消费者情绪升降，断谱=间隔超 30 分钟。
 * 图形 aria-hidden，消息列表是等价内容。
 */
export const ServiceScore = memo(function ServiceScore({ score, activeId, onPick }: {
  score: ServiceScoreView
  activeId?: string | null
  onPick?: (messageId: string) => void
}) {
  const laid = noteLayout(score.notes)
  const xOf = new Map(laid.map((item) => [item.note.messageId, item.x]))
  const width = Math.max(320, PAD + laid.length * STEP + 12)
  const customers = laid.filter((item) => item.note.role === 'customer' && item.note.level)
  const yOf = (note: Note) => TOP + STAFF_GAP * PITCH[note.level ?? 'calm']
  const breaks = new Set(score.breaks.map((item) => item.beforeMessageId))
  const labelled = laid.filter((item, i) => i === 0 || i === laid.length - 1 || breaks.has(item.note.messageId))
  return <div className="yt-score" aria-hidden="true">
    <svg width={width} height={SCORE_HEIGHT} viewBox={`0 0 ${width} ${SCORE_HEIGHT}`}>
      {(['激烈', '不满', '平稳'] as const).map((name, i) => <g key={name}>
        <text x={0} y={TOP + STAFF_GAP * i + 4} className="yt-score-label">{name}</text>
        <line x1={PAD - 12} x2={width} y1={TOP + STAFF_GAP * i} y2={TOP + STAFF_GAP * i} className="yt-score-staff" />
      </g>)}
      <text x={0} y={SERVICE_Y + 4} className="yt-score-label">服务方</text>
      <line x1={PAD - 12} x2={width} y1={SERVICE_Y} y2={SERVICE_Y} className="yt-score-staff" />
      {customers.slice(1).map((item, i) => {
        const prev = customers[i]
        const delta = PITCH[prev.note.level!] - PITCH[item.note.level!]
        if (!delta) return null
        const y = TOP + STAFF_GAP * 2 + 14
        const x1 = prev.x + 4
        const x2 = item.x - 4
        return <path key={`h-${item.note.messageId}`} className={delta > 0 ? 'yt-score-up' : 'yt-score-down'}
          d={delta > 0 ? `M${x1} ${y} L${x2} ${y - 4} M${x1} ${y} L${x2} ${y + 4}` : `M${x1} ${y - 4} L${x2} ${y} M${x1} ${y + 4} L${x2} ${y}`} />
      })}
      {score.waits.map((wait) => {
        const x1 = xOf.get(wait.fromMessageId)
        const x2 = wait.toMessageId ? xOf.get(wait.toMessageId) : undefined
        if (x1 == null || x2 == null) return null
        const over = wait.ms > 120000
        return <g key={`w-${wait.fromMessageId}`}>
          <rect x={x1} y={SERVICE_Y - 2.5} width={Math.max(2, x2 - x1 - 6)} height={5} rx={2} className={over ? 'yt-score-rest is-over' : 'yt-score-rest'} />
          {over && <text x={x2 - 4} y={SERVICE_Y + 16} textAnchor="end" className="yt-score-wait">{minutes(wait.ms)}</text>}
        </g>
      })}
      {laid.map(({ note, x }) => {
        const on = note.messageId === activeId
        if (note.role === 'customer') {
          const y = yOf(note)
          return <g key={note.messageId} className={`yt-score-note${on ? ' is-on' : ''}`} onClick={() => onPick?.(note.messageId)}>
            {note.signals.length > 0 && <path d={`M${x - 4} ${y - 9} L${x} ${y - 13} L${x + 4} ${y - 9}`} className="yt-score-accent" />}
            <ellipse cx={x} cy={y} rx={on ? 6 : 4.5} ry={on ? 4.6 : 3.5} transform={`rotate(-20 ${x} ${y})`}
              fill={note.level ? COLOR[note.level] : 'var(--yt-silent)'} className="yt-score-head" />
          </g>
        }
        const ai = note.role === 'assistant'
        return <rect key={note.messageId} x={x - 4} y={SERVICE_Y - 4} width={8} height={8} rx={1}
          className={`yt-score-svc${ai ? ' is-ai' : ''}${on ? ' is-on' : ''}`} onClick={() => onPick?.(note.messageId)} />
      })}
      {laid.filter(({ note }) => breaks.has(note.messageId)).map(({ note, x }) =>
        <text key={`b-${note.messageId}`} x={x - STEP / 2} y={AXIS_Y + 4} textAnchor="middle" className="yt-score-break">//</text>)}
      {labelled.map(({ note, x }) => <text key={`t-${note.messageId}`} x={x} y={AXIS_Y + 12} textAnchor="middle" className="yt-score-time">
        {shHourMinute(note.at)}</text>)}
    </svg>
  </div>
})
