import { Tooltip } from 'antd'
import type { LaneRow } from './traceModel'

const LABEL_W = 108
const ROW_H = 26

/** 视图 1：时序泳道。Agent 条深紫、模型调用香槟金、程序节点灰；决策为菱形；跳过虚线并写原因。 */
export function TraceTimeline({ rows, total, lit, selected, onSelect }: {
  rows: LaneRow[]; total: number; lit: Set<string> | null; selected?: string; onSelect: (spanId: string) => void
}) {
  const W = 760
  const x = (v: number) => LABEL_W + (Math.max(0, v) / total) * (W - LABEL_W - 16)
  const ticks = Array.from({ length: 6 }, (_, i) => (total / 5) * i)
  const H = rows.length * ROW_H + 26
  return <svg className="yt-tl" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="时序泳道">
    {ticks.map((v) => <g key={v}><line x1={x(v)} x2={x(v)} y1={0} y2={H - 18} className="yt-tl-grid" />
      <text x={x(v)} y={H - 4} className="yt-tl-tick">{(v / 1000).toFixed(1)}s</text></g>)}
    {rows.map((r, i) => {
      const y = i * ROW_H + 4
      const on = !lit || lit.has(r.spanId)
      const cls = `yt-tl-row is-${r.kind} is-${r.status}${on ? '' : ' is-dim'}${selected === r.spanId ? ' is-sel' : ''}${r.group ? ' is-par' : ''}`
      const w = Math.max(3, x(r.end) - x(r.start))
      const tip = <span>{r.label} · {r.status === 'skipped' ? `跳过${r.note ? `：${r.note}` : ''}` : `${((r.end - r.start) / 1000).toFixed(2)}s`}
        {r.span.modelReturned ? <><br />{r.span.modelReturned} {r.span.promptTokens ?? 0}→{r.span.completionTokens ?? 0}</> : null}
        {r.kind === 'decision' && r.note ? <><br />{r.note}</> : null}</span>
      return <g key={r.spanId} className={cls} onClick={() => onSelect(r.spanId)} role="button" aria-label={r.label}>
        <text x={r.group ? 14 : 4} y={y + 15} className="yt-tl-label">{r.label}</text>
        <Tooltip title={tip}><g>
          {r.kind === 'decision'
            ? <path d={`M${x(r.start)} ${y + 3} l7 8 l-7 8 l-7 -8 z`} className="yt-tl-dec" />
            : <rect x={x(r.start)} y={y + 4} width={w} height={14} rx={3} className="yt-tl-bar" />}
          {r.models.map((m) => <rect key={m.spanId} x={x(m.start)} y={y + 7} width={Math.max(2, x(m.end) - x(m.start))} height={8} rx={2} className="yt-tl-model" />)}
          {r.status === 'skipped' && <text x={x(r.start) + 10} y={y + 15} className="yt-tl-note">跳过{r.note ? ` · ${r.note}` : ''}</text>}
        </g></Tooltip>
      </g>
    })}
  </svg>
}
