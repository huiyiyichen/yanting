import type { ReactNode } from 'react'

type Highlight = { start: number; end: number; kind: string }

/** 按规则返回的偏移给触发词加下划线；越界或重叠的位置直接忽略，原文完整保留。 */
export function HighlightedText({ text, highlights }: { text: string; highlights?: Highlight[] | null }) {
  const valid = [...(highlights ?? [])]
    .filter((item) => item.start >= 0 && item.end <= text.length && item.start < item.end)
    .sort((a, b) => a.start - b.start)
  const parts: ReactNode[] = []
  let cursor = 0
  for (const item of valid) {
    if (item.start < cursor) continue
    if (item.start > cursor) parts.push(text.slice(cursor, item.start))
    parts.push(<mark key={item.start} className={`yt-trigger is-${item.kind}`}>{text.slice(item.start, item.end)}</mark>)
    cursor = item.end
  }
  parts.push(text.slice(cursor))
  return <>{parts}</>
}
