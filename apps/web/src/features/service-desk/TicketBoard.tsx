import { Tag } from 'antd'
import type { TicketView } from '../../api/client'
import { dateLabel, priorities, ticketTypes } from './shared'
import { ticketDeadline } from './ticketDeadline'

const COLUMNS: { name: string; match: (status: TicketView['status']) => boolean }[] = [
  { name: '待受理', match: (s) => s === 'pending' },
  { name: '处理中', match: (s) => s === 'in_progress' },
  { name: '等待反馈', match: (s) => s.startsWith('waiting_') },
  { name: '已完成', match: (s) => s === 'resolved' },
]
/** 卡片副行：标题已含的类型/客户不再重复，补上工单号。 */
export function boardMeta(row: TicketView): string {
  return [ticketTypes[row.workOrderType], row.buyerAlias].filter((part) => part && !row.title.includes(part))
    .concat(row.ticketId).join(' · ')
}
const RANK = { overdue: 0, soon: 1, scheduled: 2, none: 3 } as const

/** 工单看板：只读分组，状态修改仍走详情表单（带版本号）。列内到期优先，再按截止时间。 */
export function TicketBoard({ rows, now, onOpen }: { rows: TicketView[]; now: number; onOpen: (ticketId: string) => void }) {
  const due = (row: TicketView) => (row.dueAt ? Date.parse(row.dueAt) : Infinity)
  return <div className="yt-board">
    {COLUMNS.map((column) => {
      const items = rows.filter((row) => column.match(row.status))
        .sort((a, b) => RANK[ticketDeadline(a, now)] - RANK[ticketDeadline(b, now)] || due(a) - due(b))
      return <section key={column.name} className="yt-board-col" aria-label={column.name}>
        <h3>{column.name}<span>{items.length}</span></h3>
        <div className="yt-board-list">
          {items.map((row) => {
            const deadline = ticketDeadline(row, now)
            return <button key={row.ticketId} type="button" data-ticket={row.ticketId}
              className={`yt-board-card${deadline === 'overdue' ? ' is-overdue' : ''}`} onClick={() => onOpen(row.ticketId)}>
              <strong>{row.title}</strong>
              <span className="yt-board-meta">{boardMeta(row)}</span>
              <span className="yt-board-foot">
                {['urgent', 'high'].includes(row.priority) && <Tag color="error">{priorities[row.priority]}</Tag>}
                {deadline === 'overdue' && <Tag color="error">已到期</Tag>}
                {deadline === 'soon' && <Tag color="warning">即将到期</Tag>}
                <span className="yt-board-who">{row.assignee || '待分配'}{row.dueAt ? ` · ${dateLabel(row.dueAt)}` : ''}</span>
              </span>
            </button>
          })}
        </div>
      </section>
    })}
  </div>
}
