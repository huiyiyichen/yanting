import { memo } from 'react'
import type { PanoramaItem } from '../../api/client'
import { EmotionSwatch, SWATCH_LABEL } from '../voiceprint/EmotionSwatch'
import { shHourMinute } from '../service-desk/shTime'
import { LANE_LABEL, clock, waitSeconds } from './panoramaModel'

/** 色块单元：AI 律动 + 情绪色号 + 昵称 + 等待计时或最后活动时间。 */
export const PanoramaTile = memo(function PanoramaTile({ item, now, selected, dimmed, onSelect }: {
  item: PanoramaItem
  now: number
  selected: boolean
  dimmed: boolean
  onSelect: (id: string) => void
}) {
  const wait = waitSeconds(item, now)
  const bands = item.emotionBands ?? []
  const seq = bands.map((level) => SWATCH_LABEL[level]).join('、')
  const label = [item.buyerAlias, LANE_LABEL[item.lane], seq, item.highRisk ? '高风险' : ''].filter(Boolean).join('，')
  return <button type="button" data-id={item.conversationId} aria-label={label} aria-pressed={selected}
    className={`yt-ptile${selected ? ' is-selected' : ''}${dimmed ? ' is-dim' : ''}`} onClick={() => onSelect(item.conversationId)}>
    <span className={`yt-wave yt-ptile-wave${item.aiJob === 'running' ? ' is-on' : ''}`} aria-hidden="true"><i /><i /><i /><i /><i /></span>
    <EmotionSwatch bands={bands} highRisk={item.highRisk} />
    <span className="yt-ptile-name">{item.buyerAlias}</span>
    {wait != null
      ? <span className={`yt-ptile-meta is-wait${wait >= 120 ? ' is-over' : wait >= 60 ? ' is-warn' : ''}`}>{clock(wait)}</span>
      : <span className="yt-ptile-meta">{shHourMinute(item.lastActivityAt)}</span>}
  </button>
})
