import { FileTextOutlined, PlusOutlined } from '@ant-design/icons'
import { Avatar, Button, Empty, Tooltip } from 'antd'
import type { ConsumerServiceContextView, ServiceMemoryView, TicketView } from '../../api/client'
import { TicketStatus, money, ticketTypes } from './shared'
import { shHourMinute, shMonthDay, shTimestamp } from './shTime'

const MEMORY_LABELS = { known: '已知信息', concern: '消费者关注', attempted: '已尝试措施', unresolved: '待解决事项' } as const
const stamp = (value?: string | null) => [shMonthDay(value), shHourMinute(value)].filter(Boolean).join(' ')

type Props = {
  context: ConsumerServiceContextView | null
  memory: ServiceMemoryView | null
  tickets: TicketView[]
  onOpenTicket: (ticketId: string) => void
  onNewTicket: () => void
}

/** 插件「档案」：跨会话的客户底账——身份、购买、历史进线、服务记忆、工单。 */
export function ArchivePanel({ context, memory, tickets, onOpenTicket, onNewTicket }: Props) {
  if (!context) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无档案" />
  const orders = [...new Map(context.orders.map((order) => [order.orderId, order])).values()]
    .sort((a, b) => shTimestamp(b.orderedAt) - shTimestamp(a.orderedAt))
  const paid = orders.reduce((sum, order) => sum + (order.paidAmountMinor ?? 0), 0)
  const history = (context.historyServices ?? []).filter((item) => item.conversationId !== context.conversationId)
    .sort((a, b) => shTimestamp(b.firstAt) - shTimestamp(a.firstAt))
  const aliases = context.buyerAliases.filter((alias) => alias !== context.buyerAlias)
  const memoryGroups = (Object.keys(MEMORY_LABELS) as (keyof typeof MEMORY_LABELS)[])
    .map((category) => ({ category, items: memory?.items?.filter((item) => item.category === category) ?? [] }))
    .filter((group) => group.items.length)

  return <div className="yt-archive">
    <section className="yt-arc-id" aria-label="消费者服务档案">
      <h3 className="yt-sr">消费者服务档案</h3>
      <Avatar className="yt-persona-avatar">{context.buyerAlias.slice(0, 1)}</Avatar>
      <div className="yt-arc-who">
        <strong title={context.buyerAlias}>{context.buyerAlias}</strong>
        {aliases.length > 0 && <span className="yt-arc-alias">{aliases.map((alias) => <i key={alias}>{alias}</i>)}</span>}
      </div>
      <dl className="yt-arc-kpi">
        <div><dt>进线</dt><dd>{history.length + 1}</dd></div>
        <div><dt>订单</dt><dd>{orders.length}</dd></div>
        <div><dt>累计实付</dt><dd>{money(paid)}</dd></div>
      </dl>
    </section>

    <section className="yt-arc-sec" aria-label="购买记录">
      <h3>购买记录</h3>
      <ul className="yt-arc-list">
        {orders.map((order) => <li key={order.orderId} className="yt-arc-order">
          <b title={order.productName ?? ''}>{order.productName || order.sku || order.orderId}</b>
          <span className="amt">{money(order.paidAmountMinor)}</span>
          <span className="sub">{shMonthDay(order.orderedAt)} · {order.orderId}{order.carrier ? ` · ${order.carrier}` : ''}{order.city ? ` · ${order.city}` : ''}</span>
          {order.sourceStatus && <span className="st">{order.sourceStatus}</span>}
        </li>)}
        {!orders.length && context.products?.map((product) => <li key={product.sku} className="yt-arc-order">
          <b title={product.name}>{product.name}</b><span className="amt">{money(product.unitPriceMinor)}</span>
          <span className="sub">{product.sku}</span>
        </li>)}
      </ul>
      {!orders.length && !context.products?.length && <p className="yt-empty">暂无</p>}
    </section>

    <section className="yt-arc-sec" aria-label="历史进线">
      <h3>历史进线<span className="r">{history.length} 次历史进线</span></h3>
      <ol className="yt-arc-hist">
        {history.map((item) => <li key={item.conversationId}>
          <span className="t">{stamp(item.firstAt) || item.conversationId}</span>
          <div className="b">
            <span className="tags">
              {item.relation === 'same_order' && <i className="is-order">同订单</i>}
              {item.sameTopic && <i className="is-topic">同一诉求</i>}
            </span>
            {item.latestCustomerMessage && <p title={item.latestCustomerMessage}>{item.latestCustomerMessage}</p>}
          </div>
        </li>)}
      </ol>
      {!history.length && <p className="yt-empty">首次进线</p>}
    </section>

    <section className="yt-arc-sec" aria-label="服务记忆">
      <h3>服务记忆{memory?.stale && <span className="r is-stale">待更新</span>}</h3>
      {memoryGroups.map((group) => <div className="yt-arc-mem" key={group.category}>
        <span className="k">{MEMORY_LABELS[group.category]}</span>
        <div className="v">{group.items.map((item, index) => <Tooltip key={`${item.sourceRef}-${index}`} title={item.label || undefined}>
          <span className="yt-memory-tag">{item.quote}</span>
        </Tooltip>)}</div>
      </div>)}
      {!memoryGroups.length && <p className="yt-empty">暂无</p>}
    </section>

    <section className="yt-arc-sec" aria-label="工单">
      <h3>工单<span className="r">{tickets.length}</span>
        <Button size="small" type="text" className="yt-arc-new" icon={<PlusOutlined />} onClick={onNewTicket}>新建工单</Button></h3>
      {tickets.map((ticket) => <button type="button" className="yt-arc-ticket" key={ticket.ticketId} onClick={() => onOpenTicket(ticket.ticketId)}>
        <FileTextOutlined /><b>{ticketTypes[ticket.workOrderType]}</b><span>{ticket.ticketId}</span><TicketStatus status={ticket.status} />
      </button>)}
      {!tickets.length && <p className="yt-empty">暂无</p>}
    </section>
  </div>
}
