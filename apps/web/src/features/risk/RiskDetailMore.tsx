import { MessageOutlined } from '@ant-design/icons'
import { Button, Timeline } from 'antd'
import type { RiskIncidentDetailView } from '../../api/client'
import { serviceRiskTypeLabels } from '../../contracts/enums'
import { shTimestamp } from '../service-desk/shTime'
import { HighlightedText } from '../service-desk/HighlightedText'
import { TicketStatus, dateLabel } from '../service-desk/shared'

/** 风险详情底部折叠区：服务轨迹、证据引用、关联工单（自 RiskDashboardPage 拆出）。 */
export type EvidenceItem = RiskIncidentDetailView['evidence'][number]

export function EvidenceQuote({ evidence, fallbackId, detail, onOpen }: {
  evidence: EvidenceItem
  fallbackId?: string
  detail: RiskIncidentDetailView | null
  onOpen: (conversationId: string) => void
}) {
  const conversationId = evidence.conversationId ?? (evidence.kind.includes('message') || evidence.kind === 'history_context'
    ? (detail?.incident.conversationIds.includes(evidence.label) || detail?.contactHistory?.some((point) => point.label === evidence.label)
      ? evidence.label : fallbackId) : undefined)
  return <blockquote className="evidence-quote">
    <div className="section-title-row"><span>{dateLabel(evidence.occurredAt)} · {evidence.label}</span>
      {conversationId && <Button size="small" type="text" icon={<MessageOutlined />} onClick={() => onOpen(conversationId)}>打开会话</Button>}</div>
    <p><HighlightedText text={evidence.body} highlights={evidence.highlights} /></p>
  </blockquote>
}

/** 处置记录页签：处置记录、判断复核、历史轮次合并，按时间倒序（全景方案 4.8）。 */
export function RiskHandling({ detail, onOpen }: { detail: RiskIncidentDetailView; onOpen: (conversationId: string) => void }) {
  const events = [
    ...detail.handlingHistory.map((event) => ({ key: event.eventId, at: event.createdAt, title: `${event.actor}`, body: event.note })),
    ...(detail.judgmentHistory ?? []).map((item) => ({ key: item.judgmentId, at: item.createdAt, title: `${item.actor} · 判断复核`, body: item.note || item.verdict })),
  ].sort((a, b) => shTimestamp(b.at) - shTimestamp(a.at))
  const episodes = detail.episodes ?? []
  if (!events.length && !episodes.length) return <p className="yt-empty">暂无处置记录</p>
  return <>
    {events.length > 0 && <Timeline items={events.map((event) => ({
      key: event.key, content: <div><span>{dateLabel(event.at)} · {event.title}</span><p>{event.body}</p></div>,
    }))} />}
    {episodes.map((episode) => <section className="service-section" key={`${episode.alertId}-${episode.episode}`}>
      <h3>第 {episode.episode} 轮 · {serviceRiskTypeLabels[episode.riskType as keyof typeof serviceRiskTypeLabels] ?? episode.riskType}</h3>
      <p>{dateLabel(episode.closedAt)} · {episode.handledBy}</p><p>{episode.handledNote}</p>
      {episode.evidence.map((item) => <EvidenceQuote key={item.ref} evidence={item} detail={detail} onOpen={onOpen} />)}
    </section>)}
  </>
}

export function RiskTicketList({ tickets, primaryId, onNavigate }: {
  tickets: RiskIncidentDetailView['tickets']
  primaryId?: string
  onNavigate: (path: string) => void
}) {
  return <>
    <Button disabled={!primaryId} onClick={() => primaryId && onNavigate(`/platform/work-orders?conversation=${encodeURIComponent(primaryId)}&create=1`)}>新建跟进工单</Button>
    {tickets.map((ticket) => <section className="service-section" key={ticket.ticketId}>
      <div className="section-title-row"><strong>{ticket.title}</strong><TicketStatus status={ticket.status} /></div>
      <p>{ticket.assignee || '待分配'} · {ticket.ticketId}</p>
      <Button size="small" onClick={() => onNavigate(`/platform/work-orders?ticket=${encodeURIComponent(ticket.ticketId)}`)}>打开工单</Button>
    </section>)}
  </>
}
