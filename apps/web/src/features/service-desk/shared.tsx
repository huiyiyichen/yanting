import { Descriptions, Empty, Tag, Timeline } from 'antd'
import type { ConsumerServiceContextView, TicketView } from '../../api/client'

export const ticketTypes: Record<TicketView['workOrderType'], string> = {
  reship_exchange: '补发换货', offline_payment: '线下打款', logistics: '物流',
  adverse_reaction: '不良反应', return_refund: '售后退货',
}
export const ticketStatuses: Record<TicketView['status'], string> = {
  pending: '待受理', in_progress: '处理中', waiting_customer: '等待客户',
  waiting_internal: '等待内部', resolved: '已完成',
}
export const priorities: Record<TicketView['priority'], string> = {
  low: '低', normal: '普通', high: '高', urgent: '紧急',
}
export const dateLabel = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN', {
  month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
}) : '未设置'
export const optionsOf = (labels: Record<string, string>) => Object.entries(labels).map(([value, label]) => ({ value, label }))
export const money = (value?: number | null) => value == null ? '暂无金额' : `¥${(value / 100).toFixed(2)}`

export function TicketStatus({ status }: { status: TicketView['status'] }) {
  return <Tag color={status === 'resolved' ? 'success' : status === 'pending' ? 'default' : 'processing'}>{ticketStatuses[status]}</Tag>
}

export function OrderFacts({ context }: { context: ConsumerServiceContextView | null }) {
  if (!context) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联订单" />
  return <div>
    {!context.orders.length && context.products?.map((product) => <section className="service-section" key={product.name}>
      <h3>{product.name}</h3><p>{product.sku}</p><p>{money(product.unitPriceMinor)}</p>
    </section>)}
    {!context.orders.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无关联订单" />}
    {context.orders.map((order) => <section className="service-section" key={order.orderId}>
    <div className="section-title-row"><strong>{order.productName}</strong><Tag>{order.sourceStatus}</Tag></div>
    <Descriptions column={1} size="small" items={[
      { key: 'id', label: '订单号', children: order.orderId },
      { key: 'sku', label: '商品货号', children: order.sku || '未提供' },
      { key: 'money', label: '实付 / 数量', children: `${money(order.paidAmountMinor)} / ${order.quantity ?? 0} 件` },
      { key: 'tracking', label: '物流', children: [order.carrier, order.trackingNo].filter(Boolean).join(' · ') || '暂无物流' },
      { key: 'time', label: '下单时间', children: dateLabel(order.orderedAt) },
      { key: 'gift', label: '赠品', children: order.gift || '无' },
    ]} />
  </section>)}</div>
}

export function ServiceTimeline({ context }: { context: ConsumerServiceContextView | null }) {
  const serviceNodes = context?.serviceNodes ?? []
  const messageEvents = (context?.timeline ?? []).filter((event) => event.message?.body)
  if (!serviceNodes.length && !messageEvents.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无服务记录" />
  return <><p>进线次数 <Tag>{1 + (context?.historyConversationIds?.length ?? 0)}</Tag>
    {context?.historyConversationIds?.length ? <span className="risk-contact-links">关联历史会话：{context.historyConversationIds.join('、')}</span> : null}
  </p>{serviceNodes.length ? <Timeline items={serviceNodes.map((node, index) => ({
    key: `${node.sourceRecordId}-${index}`,
    content: <div className="service-node-content"><small>{dateLabel(node.occurredAt)}</small>
      <strong>{node.kind}</strong><span>{node.title}</span>{node.status && <Tag>{node.status}</Tag>}
    </div>,
  }))} /> : null}
  {messageEvents.length ? <section className="service-message-track">
    <div className="section-title-row"><strong>聊天轨迹</strong><Tag>{messageEvents.length} 条消息</Tag></div>
    <Timeline items={messageEvents.map((event) => ({
      key: event.eventId,
      content: <div className="service-message-content">
        <small>{dateLabel(event.occurredAt)} · {event.message?.senderRole === 'customer' ? '消费者' : '客服'}</small>
        <p>{event.message?.body}</p>
      </div>,
    }))} />
  </section> : null}</>
}
