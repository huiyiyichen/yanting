/**
 * 触发词高亮（P1-6）。先列失败方式：
 * T1 高亮位置错位，标出的文字不是命中词。
 * T2 越界或重叠的位置导致原文缺字、重复或渲染报错（原文必须完整保留）。
 * T3 类型样式丢失：激烈/投诉与不满不可区分。
 * T4 没有高亮时渲染出额外标记。
 */
import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { HighlightedText } from './HighlightedText'

describe('HighlightedText', () => {
  it('T1 T3 marks the exact span with its kind', () => {
    const { container } = render(<HighlightedText text="太过分了，我要投诉" highlights={[
      { start: 1, end: 3, kind: 'dissatisfied' }, { start: 7, end: 9, kind: 'complaint' }]} />)
    const marks = [...container.querySelectorAll('mark')]
    expect(marks.map((m) => [m.textContent, m.className])).toEqual([
      ['过分', 'yt-trigger is-dissatisfied'], ['投诉', 'yt-trigger is-complaint']])
    expect(container.textContent).toBe('太过分了，我要投诉')
  })
  it('T2 tolerates bad offsets and keeps full text', () => {
    const { container } = render(<HighlightedText text="我要投诉" highlights={[
      { start: 2, end: 4, kind: 'complaint' }, { start: 3, end: 9, kind: 'angry' }, { start: -1, end: 1, kind: 'angry' }]} />)
    expect(container.textContent).toBe('我要投诉')
    expect(container.querySelectorAll('mark')).toHaveLength(1)
  })
  it('T4 plain text without highlights', () => {
    const { container } = render(<HighlightedText text="好的" highlights={[]} />)
    expect(container.querySelectorAll('mark')).toHaveLength(0)
    expect(container.textContent).toBe('好的')
  })
})
