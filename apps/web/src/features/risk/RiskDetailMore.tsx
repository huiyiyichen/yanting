import { FileTextOutlined, MessageOutlined } from '@ant-design/icons'
import { Button, Collapse, Space, Tag, Timeline } from 'antd'
import type { RiskIncidentDetailView } from '../../api/client'
import { serviceRiskTypeLabels } from '../../contracts/enums'
import { EmotionArc } from '../service-desk/EmotionArc'
import { HighlightedText } from '../service-desk/HighlightedText'
import { OrderFacts, ServiceTimeline, TicketStatus, dateLabel } from '../service-desk/shared'

/** 风险详情底部折叠区：服务轨迹、证据引用、关联工单（自 RiskDashboardPage 拆出）。 */
export type EvidenceItem = RiskIncidentDetailView['evidence'][number]
const emotionLabels: Record<string, string> = { calm: '平稳', dissatisfied: '不满', angry: '激烈', unknown: '未知' }

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

export function RiskTrajectory({ detail, onOpen, onCreateTicket }: {
  detail: RiskIncidentDetailView
  onOpen: (conversationId: string) => void
  onCreateTicket: (conversationId: string) => void
}) {
  return <>
    <EmotionArc
      history={detail.emotionHistory ?? []}
      servicePoints={detail.servicePoints ?? []}
      comparisons={detail.emotionComparisons ?? []}
      onOpenConversation={onOpen}
    />
    {Boolean(detail.emotionHistory?.length) && <section className="service-section"><h3>消费者消息</h3>
      <Timeline items={detail.emotionHistory?.map((point) => ({
        key: point.messageId, content: <div className="service-message-content">
          <div className="section-title-row"><Space><Tag color={point.emotion === 'angry' ? 'error' : point.emotion === 'dissatisfied' ? 'warning' : 'success'}>{emotionLabels[point.emotion]}</Tag>
            <span>{dateLabel(point.occurredAt)} · {point.conversationId}</span></Space>
            <Button type="text" size="small" icon={<MessageOutlined />} aria-label={`打开会话 ${point.conversationId}`} onClick={() => onOpen(point.conversationId)} /></div>
          <p>{point.body}</p>
        </div>,
      }))} />
    </section>}
    {Boolean(detail.contactHistory?.length) && <section className="service-section"><h3>历史进线</h3>
      {detail.contactHistory?.map((item) => <EvidenceQuote key={item.ref} evidence={item} fallbackId={item.label} detail={detail} onOpen={onOpen} />)}
    </section>}
    {detail.contexts.map((context) => <section className="service-section" key={context.conversationId}>
      <div className="section-title-row"><strong>{context.conversationId}</strong>
        <Space>
          <Button size="small" icon={<MessageOutlined />} onClick={() => onOpen(context.conversationId)}>打开会话</Button>
          <Button size="small" icon={<FileTextOutlined />} aria-label={`为会话 ${context.conversationId} 新建工单`}
            title="为此会话新建工单"
            onClick={() => onCreateTicket(context.conversationId)} />
        </Space></div>
      <OrderFacts context={context} /><ServiceTimeline context={context} />
    </section>)}
    {detail.handlingHistory.length > 0 && <Collapse ghost items={[{
      key: 'handling', label: '处置记录', children: <Timeline items={detail.handlingHistory.map((event) => ({
        key: event.eventId, content: <div><span>{dateLabel(event.createdAt)} · {event.actor}</span><p>{event.note}</p></div>,
      }))} />,
    }]} />}
    {Boolean(detail.episodes?.length) && <Collapse ghost items={[{
      key: 'episodes', label: '历史轮次', children: detail.episodes?.map((episode) => <section className="service-section" key={`${episode.alertId}-${episode.episode}`}>
        <h3>第 {episode.episode} 轮 · {serviceRiskTypeLabels[episode.riskType as keyof typeof serviceRiskTypeLabels] ?? episode.riskType}</h3>
        <p>{dateLabel(episode.closedAt)} · {episode.handledBy}</p><p>{episode.handledNote}</p>
        {episode.evidence.map((item) => <EvidenceQuote key={item.ref} evidence={item} detail={detail} onOpen={onOpen} />)}
      </section>),
    }]} />}
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
