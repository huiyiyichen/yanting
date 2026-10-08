import type { TicketView } from '../../api/client'

export function ticketDeadline(ticket: Pick<TicketView, 'dueAt' | 'status'>, now: number) {
  if (!ticket.dueAt || ticket.status === 'resolved') return 'none'
  const time = new Date(ticket.dueAt).getTime()
  if (!Number.isFinite(time)) return 'none'
  if (time <= now) return 'overdue'
  return time <= now + 24 * 60 * 60 * 1000 ? 'soon' : 'scheduled'
}
