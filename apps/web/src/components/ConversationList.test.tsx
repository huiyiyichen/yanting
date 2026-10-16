/**
 * 客户页会话列表（全景方案 5.2）失败方式：
 * L1 每行固定显示红色删除图标（应悬停/聚焦才出现）。
 * L2 标题单行截断到 3–4 个字（应允许两行）。
 */
import { render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { ConversationList } from './ConversationList'

describe('ConversationList', () => {
  it('L1/L2 删除入口带悬停类，标题两行，meta 显示时间', () => {
    render(<ConversationList ariaLabel="会话" items={[{ conversationId: 'c1', title: '这是什么成分适合孕期吗', preview: '你好', meta: '05/11 10:25' }]}
      activeId={null} loading={false} error={null} onSelect={vi.fn()} onRefresh={vi.fn()} onDelete={vi.fn()} />)
    expect(screen.getByRole('button', { name: /删除会话/ })).toHaveClass('yt-conv-del')
    expect(screen.getByText('05/11 10:25')).toBeInTheDocument()
    expect(screen.getByText('这是什么成分适合孕期吗').style.webkitLineClamp).toBe('2')
    const css = readFileSync(resolve(__dirname, '../styles/global.css'), 'utf8')
    expect(css).toMatch(/\.yt-conv-del \{ opacity: 0;/)
    expect(css).toMatch(/\.yt-conv-item:hover \.yt-conv-del/)
  })
})
