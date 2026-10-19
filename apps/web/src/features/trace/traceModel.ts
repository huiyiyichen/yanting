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

/** 后端模型调用跨度 kind 为 model_call（旧数据为 model）；过去前端只认 model，导致检查器拿不到模型输入/输出。 */
export const isModelSpan = (s: Pick<TraceSpan, 'kind'>) => s.kind === 'model_call' || s.kind === 'model'

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
  for (const s of sorted) if (isModelSpan(s) && s.parentSpanId) {
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

// ── 编排卡片树（反馈 10-18 #3）─────────────────────────────────────────────
export type CardState = 'ok' | 'fail' | 'skipped' | 'none' | 'running'
export type TraceCheck = { name: string; hit: boolean; detail: string }
/** 闸门/程序核验逐项检查（反馈 10-19 #3），记录在 reasons 的 {checks: [...]} 里 */
export function checksOf(span: Pick<TraceSpan, 'reasons'> | null | undefined): TraceCheck[] {
  for (const r of span?.reasons ?? []) if (r && typeof r === 'object' && Array.isArray((r as { checks?: unknown }).checks)) {
    return ((r as { checks: TraceCheck[] }).checks).filter((c) => c && typeof c.name === 'string')
  }
  return []
}
export type OrchCard = {
  key: string; label: string; role: string; state: CardState; summary: string
  /** 角色徽标：Leader / Worker / 闸门 / 核验 */
  badge: 'leader' | 'worker' | 'gate' | 'check' | 'agent'
  checks: TraceCheck[]
  /** 汇合点（Leader）收到的各 Worker 结果 */
  inputs: { label: string; text: string }[]
  spanId: string | null; start: number; end: number; durationMs: number | null
  model: string | null; records: number; attempts: number
  /** 运行完成但留下问题（程序核验发现问题等），卡片用琥珀描边提示 */
  issues: number
}
export type OrchRow = { key: string; title?: string; fan: boolean; cards: OrchCard[] }

const ROLE: Record<string, string> = {
  safety_gate: '闸门 · 入口', triage: 'Leader · 理解与分派', trajectory: 'Worker · 查询', knowledge: 'Worker · 检索', vision: 'Worker · 看图',
  composer: 'Leader · 汇总起草', program_check: '核验 · 程序', verifier: '核验 · 模型', output_gate: '闸门 · 输出', send_gate: '闸门 · 发送',
}
/** 编排布局：单卡行=汇合点，多卡行=并行分支。分诊只在本次真的运行时出现。 */
const LAYOUT: { key: string; names: string[]; fan?: boolean; optional?: boolean; title?: string }[] = [
  { key: 'gate', names: ['safety_gate'] },
  { key: 'triage', names: ['triage'], optional: true },
  { key: 'workers', names: ['trajectory', 'knowledge', 'vision'], fan: true, title: '并行取证' },
  { key: 'compose', names: ['composer'] },
  { key: 'checks', names: ['program_check', 'verifier'], fan: true, title: '核验' },
  { key: 'out', names: ['output_gate'] },
  { key: 'send', names: ['send_gate'] },
]
const STATE_TEXT: Record<CardState, string> = { ok: '已完成', fail: '失败', skipped: '跳过', none: '未运行', running: '运行中' }
export const cardStateText = (c: Pick<OrchCard, 'state' | 'role'>) => c.state === 'ok' && c.role.startsWith('Worker') ? '已返回结果' : STATE_TEXT[c.state]

const toState = (status: string | undefined): CardState =>
  !status ? 'none' : status === 'ok' ? 'ok' : status === 'skipped' ? 'skipped' : status === 'running' ? 'running' : 'fail'

/** 把一次追踪整理成编排卡片树：每个 Agent 一张卡（多次尝试合并，显示最后一次）。 */
export function buildOrchestration(startedAt: string, spans: TraceSpan[]): { rows: OrchRow[]; total: number } {
  const { rows: lanes, total } = buildLanes(startedAt, spans)
  const byName = new Map<string, LaneRow[]>()
  for (const r of lanes) if (!isModelSpan(r.span)) byName.set(r.span.name, [...(byName.get(r.span.name) ?? []), r])
  const descendants = (id: string) => {
    const out: TraceSpan[] = []
    const walk = (pid: string) => spans.forEach((s) => { if (s.parentSpanId === pid) { out.push(s); walk(s.spanId) } })
    walk(id)
    return out
  }
  const card = (name: string): OrchCard => {
    const hits = byName.get(name) ?? []
    const last = hits.at(-1)
    const models = hits.flatMap((h) => descendants(h.spanId)).filter(isModelSpan)
    const lastModel = models.at(-1)
    const firstReason = last?.span.reasons?.find((r) => typeof r === 'string') as string | undefined
    const state = toState(last?.status)
    const summary = last?.span.summary || firstReason || last?.span.errorDetail || last?.span.errorCode || (state === 'none' ? '本次未经过此节点' : state === 'ok' ? '已完成' : last?.note || '')
    const role = ROLE[name] ?? (last?.kind === 'decision' ? '闸门 · 决策' : 'Agent')
    const head = role.split(' · ')[0]
    return {
      key: name, label: AGENT_LABEL[name] ?? last?.span.label ?? name, role,
      badge: head === 'Leader' ? 'leader' : head === 'Worker' ? 'worker' : head === '闸门' ? 'gate' : head === '核验' ? 'check' : 'agent',
      checks: checksOf(last?.span), inputs: [],
      state, summary, spanId: last?.spanId ?? null, start: hits[0]?.start ?? 0, end: last?.end ?? 0,
      durationMs: hits.length ? hits.reduce((a, h) => a + Math.max(0, h.end - h.start), 0) : null,
      model: lastModel ? (lastModel.modelReturned || lastModel.modelRequested || null) : null,
      records: hits.length + models.length, attempts: hits.length,
      issues: last && last.kind !== 'decision' ? (last.span.reasons ?? []).filter((r) => typeof r === 'string').length : 0,
    }
  }
  const known = new Set(LAYOUT.flatMap((l) => l.names))
  const rows: OrchRow[] = []
  for (const l of LAYOUT) {
    if (l.optional && !l.names.some((n) => byName.has(n))) continue
    // 本次没经过的节点不占位（反馈 10-19 #4）
    const cards = l.names.map(card).filter((c) => c.state !== 'none' && c.state !== 'skipped')
    if (!cards.length) continue
    const fan = Boolean(l.fan) && cards.length > 1
    // 只有时间上真的重叠才叫并行；单流程里轨迹与知识是先后执行的
    const overlap = cards.some((a, i) => cards.some((b, j) => j > i && a.start < b.end && b.start < a.end))
    const title = l.key === 'workers' ? (fan ? `${overlap ? '并行' : '依次'}调用 ${cards.length} 个 Worker` : '派发') : l.key === 'checks' && fan ? '两道核验' : l.title
    rows.push({ key: l.key, title, fan, cards })
  }
  const workers = rows.find((r) => r.key === 'workers')?.cards ?? []
  const leader = rows.find((r) => r.key === 'compose')?.cards[0]
  if (leader) leader.inputs = workers.filter((w) => w.state === 'ok').map((w) => ({ label: w.label, text: w.summary }))
  const extra = [...byName.keys()].filter((n) => !known.has(n))
  if (extra.length) rows.push({ key: 'after', title: '发送后', fan: extra.length > 1, cards: extra.map(card) })
  return { rows, total }
}

export const fmtMs = (v: number | null | undefined) => v == null ? '' : v < 1000 ? `${Math.round(v)}ms` : `${(v / 1000).toFixed(1)}s`

/** 某节点下（含嵌套）的全部模型调用跨度。 */
export function modelsOf(spans: TraceSpan[], spanId: string | null): TraceSpan[] {
  if (!spanId) return []
  const out: TraceSpan[] = []
  const walk = (pid: string) => spans.forEach((s) => { if (s.parentSpanId === pid) { if (isModelSpan(s)) out.push(s); walk(s.spanId) } })
  walk(spanId)
  return out
}
