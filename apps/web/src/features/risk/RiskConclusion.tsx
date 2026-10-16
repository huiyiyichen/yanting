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
  jump?: { conversationId: string; messageId: string }
  state: string
  tools?: ReactNode
}

/** 风险结论（全景方案 4.4）：每个信号一行，原话/业务事实 + 时间跳转对话回放 + 状态胶囊。 */
export function RiskConclusion({ rows, footer, onJump }: {
  rows: ConclusionRow[]
  footer?: string | null
  onJump: (conversationId: string, messageId: string) => void
}) {
  return <section className="yt-conclusion" aria-label="风险结论">
    <h3>风险结论</h3>
    <ul>{rows.map((row) => <li key={row.key} className={`is-${row.level}`}>
      <b>{row.type}</b>
      <span className="q" title={row.text}><HighlightedText text={row.text} highlights={row.highlights} /></span>
      {row.jump ? <button type="button" className="t" aria-label={`跳到原话 ${row.type}`} onClick={() => onJump(row.jump!.conversationId, row.jump!.messageId)}>
        {shHourMinute(row.at)}<ArrowRightOutlined rotate={-45} /></button> : <span className="t">{shHourMinute(row.at)}</span>}
      <span className="s">{row.state}</span>
      {row.tools}
    </li>)}</ul>
    {footer && <p className="yt-conclusion-foot">{footer}</p>}
  </section>
}
