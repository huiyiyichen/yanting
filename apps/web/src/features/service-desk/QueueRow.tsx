import { Badge } from 'antd'
import { memo } from 'react'
import { Link } from 'react-router-dom'
import type { ReceptionItem } from '../../api/client'
import { serviceRiskTypeLabels } from '../../contracts/enums'
import { dateLabel } from './shared'

export const riskHref = (conversationId: string, risk: string) =>
  `/risk?${new URLSearchParams({ conversation: conversationId, type: risk }).toString()}`

/** 活动窗口（全景方案 8：120 分钟）；更早的会话不计等待，只显示日期。 */
export const ACTIVE_WINDOW_SECONDS = 120 * 60

/** 等待超过阈值时的等待时长；口径与后端 response_wait 规则一致（waitingSince + 阈值）。 */
export function waitLabel(item: ReceptionItem, now: number): string | null {
  if (!item.waitingSince) return null
  const seconds = Math.floor((now - Date.parse(item.waitingSince)) / 1000)
  if (!Number.isFinite(seconds) || seconds < (item.waitThresholdSeconds ?? 120) || seconds > ACTIVE_WINDOW_SECONDS) return null
  return seconds < 3600 ? `等待 ${Math.floor(seconds / 60)} 分` : `等待 1 小时 ${Math.floor((seconds - 3600) / 60)} 分`
}

type QueueRowProps = {
  item: ReceptionItem
  active: boolean
  now: number
  onOpen: (conversationId: string) => void
}

/** 轮询每 1.5 秒换一批新对象：按内容比较，只有该行可见内容变了才重渲。 */
export function sameQueueRow(prev: QueueRowProps, next: QueueRowProps): boolean {
  return prev.active === next.active
    && prev.onOpen === next.onOpen
    && waitLabel(prev.item, prev.now) === waitLabel(next.item, next.now)
    && JSON.stringify(prev.item) === JSON.stringify(next.item)
}

export const QueueRow = memo(function QueueRow({ item, active, now, onOpen }: QueueRowProps) {
  const risk = item.riskLevel === 'high' ? 'high' : item.activeRiskTypes?.length ? 'medium' : null
  const wait = waitLabel(item, now)
  // 全景方案 5.3：重复进线几乎每行都有，只在没有其他有效信号时才显示
  const activeRisk = [...(item.activeRiskTypes ?? [])].sort((a, b) => Number(a === 'repeated_contact') - Number(b === 'repeated_contact'))[0]
  const reviewRisk = activeRisk ? undefined : item.reviewRiskTypes?.[0]
  const tagRisk = activeRisk ?? reviewRisk
  return <div className={`reception-row-item yt-qi${active ? ' is-active' : ''}${risk ? ` is-risk-${risk}` : ''}`}>
    <button className={`reception-row${active ? ' is-active' : ''}`} aria-label={`${item.buyerAlias} ${item.conversationId}`} onClick={() => onOpen(item.conversationId)}>
      <Badge count={item.unreadCount} size="small" offset={[-2, 2]}>
        <span className="yt-queue-avatar">{item.buyerAlias.slice(0, 1)}
          {item.currentEmotion && <i className={`yt-emotion-dot is-${item.currentEmotion}`} />}</span>
      </Badge>
      <strong className="yt-qi-nm">{item.buyerAlias}</strong>
      {wait ? <time className="yt-qi-tm yt-queue-wait">{wait}</time> : <time className="yt-qi-tm">{dateLabel(item.updatedAt)}</time>}
      <span className="yt-qi-last">{item.preview || '新会话'}</span>
    </button>
    {tagRisk
      ? <Link className="yt-qi-tag-link" to={riskHref(item.conversationId, tagRisk)}
        aria-label={`${activeRisk ? '查看' : '复核'}${serviceRiskTypeLabels[tagRisk]} · ${item.buyerAlias}`}>
        <span data-testid="queue-tag" className={`yt-tag ${activeRisk ? (risk === 'high' ? 'is-hi' : 'is-mid') : 'is-review'}`}>
          {serviceRiskTypeLabels[tagRisk]}</span></Link>
      : item.serviceMode === 'autonomous' ? <span data-testid="queue-tag" className="yt-tag is-ai yt-qi-tag">AI</span> : null}
  </div>
})
