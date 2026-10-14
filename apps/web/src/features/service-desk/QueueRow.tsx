import { UserOutlined } from '@ant-design/icons'
import { Avatar, Badge, Tag } from 'antd'
import { Link } from 'react-router-dom'
import type { ReceptionItem } from '../../api/client'
import { serviceRiskTypeLabels } from '../../contracts/enums'
import { dateLabel } from './shared'

export const riskHref = (conversationId: string, risk: string) =>
  `/risk?${new URLSearchParams({ conversation: conversationId, type: risk }).toString()}`

/** 等待超过阈值时的等待时长；口径与后端 response_wait 规则一致（waitingSince + 阈值）。 */
export function waitLabel(item: ReceptionItem, now: number): string | null {
  if (!item.waitingSince) return null
  const seconds = Math.floor((now - Date.parse(item.waitingSince)) / 1000)
  if (!Number.isFinite(seconds) || seconds < (item.waitThresholdSeconds ?? 120)) return null
  return seconds < 3600 ? `等待 ${Math.floor(seconds / 60)} 分` : `等待 ${Math.floor(seconds / 3600)} 小时`
}

export function QueueRow({ item, active, now, onOpen }: {
  item: ReceptionItem
  active: boolean
  now: number
  onOpen: () => void
}) {
  const risk = item.riskLevel === 'high' ? 'high' : item.activeRiskTypes?.length ? 'medium' : null
  const wait = waitLabel(item, now)
  const firstRisk = item.activeRiskTypes?.[0]
  const tag = firstRisk ? serviceRiskTypeLabels[firstRisk] : item.serviceMode === 'autonomous' ? 'AI' : null
  return <div className={`reception-row-item${active ? ' is-active' : ''}${risk ? ` is-risk-${risk}` : ''}`}>
    <button className={`reception-row${active ? ' is-active' : ''}`} aria-label={`${item.buyerAlias} ${item.conversationId}`} onClick={onOpen}>
      <Badge count={item.unreadCount} size="small">
        <span className="yt-queue-avatar"><Avatar icon={<UserOutlined />} />
          {item.currentEmotion && <i className={`yt-emotion-dot is-${item.currentEmotion}`} />}</span>
      </Badge>
      <span className="reception-row-main">
        <span className="reception-row-title"><strong>{item.buyerAlias}</strong>
          {wait ? <time className="yt-queue-wait">{wait}</time> : <time>{dateLabel(item.updatedAt)}</time>}</span>
        <span className="reception-row-preview"><span className="reception-row-text">{item.preview || '新会话'}</span>
          {tag && <Tag data-testid="queue-tag" color={firstRisk ? (risk === 'high' ? 'error' : 'warning') : 'gold'}>{tag}</Tag>}</span>
      </span>
    </button>
    {item.activeRiskTypes?.length || item.reviewRiskTypes?.length ? <div className="reception-risk-links">
      {item.activeRiskTypes?.slice(0, 2).map((r) => <Link key={r} to={riskHref(item.conversationId, r)}
        aria-label={`查看${serviceRiskTypeLabels[r]} · ${item.buyerAlias}`}><Tag color="warning">{serviceRiskTypeLabels[r]}</Tag></Link>)}
      {item.reviewRiskTypes?.slice(0, 1).map((r) => <Link key={`review-${r}`} to={riskHref(item.conversationId, r)}
        aria-label={`复核${serviceRiskTypeLabels[r]} · ${item.buyerAlias}`}><Tag color="processing">待复核 · {serviceRiskTypeLabels[r]}</Tag></Link>)}
    </div> : null}
  </div>
}
