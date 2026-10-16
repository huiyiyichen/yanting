import { CarOutlined, DownOutlined, MedicineBoxOutlined, PayCircleOutlined, RightOutlined, RollbackOutlined, SwapOutlined } from '@ant-design/icons'
import { Empty, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { TicketView } from '../../api/client'
import { TicketStatus, dateLabel, priorities, ticketTypes } from './shared'
import { ticketDeadline } from './ticketDeadline'
import { dueText, groupOf, statusGroups, type StatusGroup } from './ticketList'

const TYPE_ICON: Record<string, React.ReactNode> = {
  reship_exchange: <SwapOutlined />, offline_payment: <PayCircleOutlined />, logistics: <CarOutlined />,
  adverse_reaction: <MedicineBoxOutlined />, return_refund: <RollbackOutlined />,
}

type GroupRow = { kind: 'group'; key: string; group: StatusGroup; label: string; count: number; open: boolean }
type Row = GroupRow | (TicketView & { kind: 'ticket'; key: string })

/** 工单列表：一行读完关键信息；“全部”时按状态分段，段头可折叠；打开详情时收起次要列。 */
export function TicketTable({ rows, grouped, collapsed, onToggle, selectedId, onOpen, now, compact, loading }: {
  rows: TicketView[]
  grouped: boolean
  collapsed: ReadonlySet<StatusGroup>
  onToggle: (group: StatusGroup) => void
  selectedId: string | null
  onOpen: (ticketId: string) => void
  now: number
  compact: boolean
  loading: boolean
}) {
  const data: Row[] = []
  if (grouped) for (const { key, label } of statusGroups) {
    const members = rows.filter((r) => groupOf(r.status) === key)
    if (!members.length) continue
    const open = !collapsed.has(key)
    data.push({ kind: 'group', key: `group:${key}`, group: key, label, count: members.length, open })
    if (open) data.push(...members.map((r) => ({ ...r, kind: 'ticket' as const, key: r.ticketId })))
  } else data.push(...rows.map((r) => ({ ...r, kind: 'ticket' as const, key: r.ticketId })))

  const cols: Array<ColumnsType<Row>[number] & { secondary?: boolean }> = [
    { title: '工单 / 事项', key: 'title', width: compact ? 260 : 320, render: (_, row) => row.kind === 'group'
      ? <button type="button" className="yt-ticket-group" aria-expanded={row.open} onClick={() => onToggle(row.group)}>
        {row.open ? <DownOutlined /> : <RightOutlined />}<strong>{row.label}</strong><span>{row.count}</span></button>
      : (() => {
        const due = row.dueAt ? dueText(row, now) : ''
        const state = ticketDeadline(row, now)
        return <button type="button" className="table-title-link" onClick={() => onOpen(row.ticketId)}>
          <strong><span className="yt-ticket-ic" role="img" aria-label={ticketTypes[row.workOrderType]} title={ticketTypes[row.workOrderType]}>{TYPE_ICON[row.workOrderType]}</span>
            {row.title}{['urgent', 'high'].includes(row.priority) && <Tag color="error" className="yt-ticket-pri">{priorities[row.priority]}</Tag>}</strong>
          <small>{row.ticketId}{row.dueAt && <span className={`yt-ticket-due is-${state}`}> · 跟进 {dateLabel(row.dueAt)}{due && <b> {due}</b>}</span>}</small>
        </button>
      })() },
    { title: '订单', key: 'order', width: 150, secondary: true, render: (_, row) => row.kind === 'ticket' && (row.orderId || <span className="yt-muted">—</span>) },
    { title: '状态', key: 'status', width: 92, render: (_, row) => row.kind === 'ticket' && <TicketStatus status={row.status} /> },
    { title: '负责人', key: 'assignee', width: 76, render: (_, row) => row.kind === 'ticket' && (row.assignee || <span className="yt-warn">待分配</span>) },
    { title: '更新', key: 'updated', width: 110, secondary: true, render: (_, row) => row.kind === 'ticket' && dateLabel(row.updatedAt) },
  ]
  const visible = cols.filter((c) => !(compact && c.secondary))
  const columns = visible.map((c, i) => ({ ...c, onCell: (row: Row) => row.kind === 'group' ? { colSpan: i === 0 ? visible.length : 0 } : {} }))

  return <Table<Row> className="yt-ticket-table" rowKey="key" size="small" dataSource={data} loading={loading} pagination={false}
    columns={columns} tableLayout="fixed"
    rowClassName={(row) => row.kind === 'group' ? 'yt-ticket-group-row'
      : [`is-${ticketDeadline(row, now)}`, row.ticketId === selectedId ? 'is-selected' : ''].join(' ')}
    onRow={(row) => row.kind === 'ticket' ? { 'aria-selected': row.ticketId === selectedId } as React.HTMLAttributes<HTMLElement> : {}}
    locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无工单" /> }} />
}
