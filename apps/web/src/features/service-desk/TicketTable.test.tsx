/**
 * 工单列表（全景方案 5.5）失败方式：
 * K1 “类型”“客户”两列与标题重复，挤占阅读宽度（应删列，标题前加类型图标）。
 * K2 普通优先级也打标签，满屏“普通”（只标高优先级）。
 * K3 “下次跟进”整列都是“—”（无值不占列；有值显示在标题下方并带倒计时）。
 */
import { render, screen } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { describe, expect, it, vi } from 'vitest'
import type { TicketView } from '../../api/client'
import { TicketTable } from './TicketTable'

const now = Date.parse('2026-05-10T10:00:00+08:00')
const ticket = (patch: Partial<TicketView>): TicketView => ({
  ticketId: 'T1', title: '不良反应 · 半d**', conversationId: 'S1', buyerAlias: '半d**', workOrderType: 'adverse_reaction',
  status: 'pending', priority: 'normal', createdAt: '2026-05-09T10:00:00+08:00', updatedAt: '2026-05-09T10:00:00+08:00', ...patch,
} as TicketView)
const mount = (rows: TicketView[]) => render(<ConfigProvider><TicketTable rows={rows} grouped={false} collapsed={new Set()} onToggle={vi.fn()}
  selectedId={null} onOpen={vi.fn()} now={now} compact={false} loading={false} /></ConfigProvider>)

describe('TicketTable', () => {
  it('K1 无类型/客户/下次跟进/优先级列，标题前有类型图标', () => {
    mount([ticket({})])
    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent)
    expect(headers).not.toContain('类型')
    expect(headers).not.toContain('客户')
    expect(headers).not.toContain('下次跟进')
    expect(headers).not.toContain('优先级')
    expect(screen.getByRole('img', { name: '不良反应' })).toBeInTheDocument()
  })
  it('K2/K3 只标高优先级；有跟进时间时在标题下方带倒计时', () => {
    mount([ticket({ ticketId: 'A', priority: 'high', dueAt: '2026-05-10T12:00:00+08:00', status: 'in_progress' }), ticket({ ticketId: 'B' })])
    expect(screen.getAllByText('高')).toHaveLength(1)
    expect(screen.queryByText('普通')).not.toBeInTheDocument()
    expect(screen.getByText(/还剩 2 小时/)).toBeInTheDocument()
  })
})
