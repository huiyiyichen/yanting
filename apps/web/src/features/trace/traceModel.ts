import type { components } from '../../contracts/api'

export type TraceSpan = components['schemas']['TraceSpanView']
export type TraceCitation = components['schemas']['TraceCitationView']

export const AGENT_LABEL: Record<string, string> = {
  safety_gate: '安全闸门', triage: '分诊', router: '路由', trajectory: '轨迹查询', knowledge: '知识', vision: '视觉', join: '汇合',
  composer: '共情起草', program_check: '程序核验', verify_decision: '核验决策', verifier: '核验', output_gate: '输出闸门',
  send_gate: '发送闸门', rewriter: '改写', memory: '记忆', handoff_summary: '交接摘要', sentinel: '风险哨兵',
}
export const spanLabel = (s: Pick<TraceSpan, 'name' | 'label'>) => AGENT_LABEL[s.name] ?? (s.label || s.name)

export type LaneRow = {
  spanId: string; label: string; kind: string; status: string; group: string | null; attempt: number
  start: number; end: number; note: string; models: { start: number; end: number; spanId: string }[]; span: TraceSpan
}

const ms = (iso: string | null | undefined, t0: number) => (iso ? Date.parse(iso) - t0 : 0)
const reasonText = (r: unknown) => (typeof r === 'string' ? r : r && typeof r === 'object' && 'reason' in r ? String((r as { reason: unknown }).reason) : JSON.stringify(r))

/** 时序泳道：行=闸门和 Agent（按执行顺序），模型调用是父行内的金色段。 */
export function buildLanes(startedAt: string, spans: TraceSpan[]): { rows: LaneRow[]; total: number } {
  const t0 = Date.parse(startedAt)
  const sorted = [...spans].sort((a, b) => a.seq - b.seq)
  const ids = new Set(sorted.map((s) => s.spanId))
  const rows: LaneRow[] = sorted.filter((s) => !s.parentSpanId || !ids.has(s.parentSpanId)).map((s) => {
    const start = ms(s.startedAt, t0)
    return {
      spanId: s.spanId, label: `${spanLabel(s)}${s.attempt > 1 ? ` @${s.attempt}` : ''}`, kind: s.kind, status: s.status,
      group: s.parallelGroup ?? null, attempt: s.attempt, start, end: s.endedAt ? ms(s.endedAt, t0) : start + (s.durationMs ?? 0),
      note: (s.reasons ?? []).map(reasonText).join('；'), models: [], span: s,
    }
  })
  const byId = new Map(rows.map((r) => [r.spanId, r]))
  const rootOf = (s: TraceSpan): LaneRow | undefined => {
    let cur: TraceSpan | undefined = s
    while (cur?.parentSpanId) {
      const row = byId.get(cur.parentSpanId)
      if (row) return row
      cur = sorted.find((x) => x.spanId === cur!.parentSpanId)
    }
    return undefined
  }
  for (const s of sorted) if (s.kind === 'model' && s.parentSpanId) {
    const row = rootOf(s)
    if (row) row.models.push({ start: ms(s.startedAt, t0), end: s.endedAt ? ms(s.endedAt, t0) : ms(s.startedAt, t0) + (s.durationMs ?? 0), spanId: s.spanId })
  }
  return { rows, total: Math.max(1, ...rows.map((r) => r.end)) }
}

/** 回放：按开始时间依次点亮；delay 为距上一帧的等待（真实时间 ÷ 倍速）。 */
export function replayFrames(rows: LaneRow[], speed = 1): { spanId: string; delay: number }[] {
  const order = [...rows].sort((a, b) => a.start - b.start || a.span.seq - b.span.seq)
  return order.map((r, i) => ({ spanId: r.spanId, delay: Math.round((r.start - (i ? order[i - 1].start : 0)) / speed) }))
}

export type ChainItem = { style: string; index: number; text: string; sources: { id: string; record: string | null; recordId: string | null; ok: boolean; verdict: string }[] }

/** 引用链：分段 → 来源 → 官方记录。 */
export function citationChain(citations: TraceCitation[]): ChainItem[] {
  const out = new Map<string, ChainItem>()
  for (const c of citations) {
    const key = `${c.replyStyle}#${c.segmentIndex}`
    const item = out.get(key) ?? { style: c.replyStyle, index: c.segmentIndex, text: c.segmentText, sources: [] }
    item.sources.push({ id: c.sourceId, record: c.sheetName ? `${c.sheetName} 第 ${c.rowNumber} 行` : null,
      recordId: c.sourceRecordId ?? null, ok: c.verdict === 'verified', verdict: c.verdict })
    out.set(key, item)
  }
  return [...out.values()].sort((a, b) => a.style.localeCompare(b.style) || a.index - b.index)
}
