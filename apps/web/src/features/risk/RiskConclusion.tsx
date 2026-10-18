import { ArrowRightOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'
import { HighlightedText } from '../service-desk/HighlightedText'
import { shHourMinute } from '../service-desk/shTime'

export type ConclusionRow = {
  key: string
  level: 'high' | 'medium' | 'low' | string
  type: string
  /** 有原话时为原话；无原话时为业务事实 */
  text: string
  highlights?: { start: number; end: number; kind: string }[]
  at?: string | null
  /** 点击整行跳到对话回放；messageId 为空时按 riskType/at 找最近的消息 */
  jump?: { conversationId: string; messageId: string; riskType?: string; at?: string | null }
  /** 只显示有意义的状态（当前触发/待复核/已标误报）；空则不占位 */
  state?: string | null
  tools?: ReactNode
}

/** 风险结论（全景方案 4.4）：每个信号一行，原话/业务事实 + 时间跳转对话回放 + 状态胶囊。 */
export function RiskConclusion({ rows, footer, onJump }: {
  rows: ConclusionRow[]
  footer?: string | null
  onJump: (conversationId: string, messageId: string, hint?: { riskType?: string; at?: string | null }) => void
}) {
  const go = (row: ConclusionRow) => row.jump && onJump(row.jump.conversationId, row.jump.messageId, { riskType: row.jump.riskType, at: row.jump.at ?? row.at })
  return <section className="yt-conclusion" aria-label="风险结论">
    <h3>风险结论</h3>
    <ul>{rows.map((row) => <li key={row.key} className={`is-${row.level}${row.jump ? ' is-link' : ''}`}
      role={row.jump ? 'button' : undefined} tabIndex={row.jump ? 0 : undefined}
      aria-label={row.jump ? `跳到对话回放 ${row.type}` : undefined} title={row.jump ? '在对话回放中查看' : undefined}
      onClick={() => go(row)}
      onKeyDown={(event) => { if (row.jump && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); go(row) } }}>
      <b>{row.type}</b>
      <span className="q" title={row.text}><HighlightedText text={row.text} highlights={row.highlights} /></span>
      <span className="t">{shHourMinute(row.at)}{row.jump && <ArrowRightOutlined rotate={-45} />}</span>
      {row.state ? <span className="s">{row.state}</span> : null}
      {row.tools && <span className="tools" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>{row.tools}</span>}
    </li>)}</ul>
    {footer && <p className="yt-conclusion-foot">{footer}</p>}
  </section>
}
