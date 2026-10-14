/**
 * 客服视角消息情绪呈现（P1-1）。先列失败方式：
 * E1 不满/激烈的消费者消息没有情绪色边或文字；平稳消息误显示情绪文字。
 * E2 情绪升级那条消息之前没有分隔线，或分隔线出现在别处、出现多次。
 * E3 AI 发出的消息与人工客服头像无法区分。
 * E4 客户视角出现情绪或升级等内部信息。
 */
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { MessageView } from '../api/client'
import { MessageList } from './MessageList'

const msg = (id: string, senderRole: string, body: string): MessageView => ({
  messageId: id, conversationId: 'c1', senderRole: senderRole as MessageView['senderRole'], body,
  messageRevision: 1, attachments: [], createdAt: '2026-05-07T10:00:00+00:00',
})
const messages = [msg('m1', 'customer', '快递到哪了'), msg('m2', 'assistant', '我帮您查'),
  msg('m3', 'customer', '你们等着瞧'), msg('m4', 'operator', '非常抱歉')]
const emotions = { m1: 'calm', m3: 'angry' } as const

describe('MessageList emotion (support)', () => {
  it('E1 E2 E3 marks emotion, divider and AI avatar', () => {
    const { container } = render(<MessageList messages={messages} viewRole="support" emotions={emotions} escalationMessageId="m3" />)
    expect(screen.getAllByText('激烈')).toHaveLength(1)
    expect(screen.queryByText('平稳')).toBeNull()
    expect(container.querySelectorAll('[data-emotion="angry"]').length).toBeGreaterThan(0)
    const dividers = screen.getAllByRole('separator')
    expect(dividers).toHaveLength(1)
    expect(within(dividers[0]).getByText('情绪升级')).toBeTruthy()
    const order = [...container.querySelectorAll('[role="separator"], [data-message-id]')].map((el) => el.getAttribute('data-message-id') ?? 'divider')
    expect(order).toEqual(['m1', 'm2', 'divider', 'm3', 'm4'])
    expect(container.querySelector('[data-message-id="m2"] .yt-ai-avatar')).toBeTruthy()
    expect(container.querySelector('[data-message-id="m4"] .yt-ai-avatar')).toBeNull()
  })
  it('E4 customer view shows nothing internal', () => {
    const { container } = render(<MessageList messages={messages} viewRole="customer" emotions={emotions} escalationMessageId="m3" />)
    expect(screen.queryByText('激烈')).toBeNull()
    expect(screen.queryByRole('separator')).toBeNull()
    expect(container.querySelector('[data-emotion]')).toBeNull()
  })
})
