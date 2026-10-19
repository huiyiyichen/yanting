import type { components } from '../../contracts/api'

export type TraceSpan = components['schemas']['TraceSpanView']
export type TraceCitation = components['schemas']['TraceCitationView']

export const AGENT_LABEL: Record<string, string> = {
  safety_gate: '安全闸门', triage: '分诊', router: '路由', trajectory: '轨迹查询', knowledge: '知识', vision: '视觉', understand: '意图情绪', join: '汇合',
  composer: '共情起草', program_check: '程序核验', verify_decision: '核验决策', verifier: '核验', output_gate: '输出闸门',
  send_gate: '发送闸门', handoff: '人工接续', rewriter: '改写', memory: '记忆', handoff_summary: '交接摘要', sentinel: '风险哨兵',
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
  badge: 'leader' | 'worker' | 'gate' | 'check' | 'agent' | 'send' | 'human'
  checks: TraceCheck[]
  /** 本次转人工由这个节点触发 */
  trigger?: boolean
  /** 汇合点（Leader）收到的各 Worker 结果 */
  inputs: { label: string; text: string }[]
  spanId: string | null; start: number; end: number; durationMs: number | null
  model: string | null; records: number; attempts: number
  /** 运行完成但留下问题（程序核验发现问题等），卡片用琥珀描边提示 */
  issues: number
}
export type OrchRow = { key: string; title?: string; fan: boolean; cards: OrchCard[] }
/** 修复回路（阶段 5）：起草 → 核验未过 → 重新起草。from 是打回草稿的那道核验。 */
export type RepairLoop = { from: string; fromKey: string; reason: string; attempts: number; spanId: string | null }

/** 起草跨度出现第 2 次时，找出它之前最近一次留下问题的核验节点作为回路起点。 */
export function repairLoopOf(spans: TraceSpan[]): RepairLoop | null {
  const top = [...spans].filter((s) => !isModelSpan(s)).sort((a, b) => a.seq - b.seq)
  const composes = top.filter((s) => s.name === 'composer')
  const retry = composes.find((s, i) => i > 0 || s.attempt > 1)
  if (!retry || composes.length < 2) return null
  const before = top.filter((s) => s.seq < retry.seq && (s.name === 'program_check' || s.name === 'verifier'))
  const gate = before.at(-1)
  const reason = (gate?.reasons ?? []).find((r): r is string => typeof r === 'string') ?? ''
  return { from: gate ? (AGENT_LABEL[gate.name] ?? gate.name) : '核验', fromKey: gate?.name ?? 'verifier', reason,
    attempts: composes.length, spanId: gate?.spanId ?? null }
}

const ROLE: Record<string, string> = {
  safety_gate: '闸门 · 入口', triage: 'Leader · 理解与分派', trajectory: 'Worker · 查询', knowledge: 'Worker · 检索', vision: 'Worker · 看图', understand: 'Worker · 理解',
  composer: 'Leader · 汇总起草', program_check: '核验 · 程序', verifier: '核验 · 模型', output_gate: '闸门 · 输出', send_gate: '闸门 · 发送',
}
/** 编排布局：单卡行=汇合点，多卡行=并行分支。分诊只在本次真的运行时出现。 */
const LAYOUT: { key: string; names: string[]; fan?: boolean; optional?: boolean; title?: string }[] = [
  { key: 'gate', names: ['safety_gate'] },
  { key: 'triage', names: ['triage'], optional: true },
  { key: 'workers', names: ['trajectory', 'knowledge', 'understand', 'vision'], fan: true, title: '并行取证' },
  { key: 'compose', names: ['composer'] },
  { key: 'checks', names: ['program_check', 'verifier'], fan: true, title: '核验' },
  { key: 'out', names: ['output_gate'] },
]
/** 发送闸门与人工接续并入末尾的分叉（AI 自动发送 / 人工接续），不再单独占一行。 */
const FORK_NAMES = ['send_gate', 'handoff']
const STATE_TEXT: Record<CardState, string> = { ok: '已完成', fail: '失败', skipped: '跳过', none: '未运行', running: '运行中' }
export const cardStateText = (c: Pick<OrchCard, 'state' | 'role'>) => c.state === 'ok' && c.role.startsWith('Worker') ? '已返回结果' : STATE_TEXT[c.state]

const toState = (status: string | undefined): CardState =>
  !status ? 'none' : status === 'ok' ? 'ok' : status === 'skipped' ? 'skipped' : status === 'running' ? 'running' : 'fail'

/** 把一次追踪整理成编排卡片树：每个 Agent 一张卡（多次尝试合并，显示最后一次）。 */
export function buildOrchestration(startedAt: string, spans: TraceSpan[]): { rows: OrchRow[]; total: number; repair: RepairLoop | null } {
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
  const known = new Set([...LAYOUT.flatMap((l) => l.names), ...FORK_NAMES])
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
  return { rows, total, repair: repairLoopOf(spans) }
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

// ── 结局分叉：AI 自动发送 / 人工接续（反馈 10-20）────────────────────────────
export type ForkPath = 'send' | 'handoff' | 'pending' | 'none'
export type HandoffRule = { key: string; codes: string[]; name: string; detail: string; nodes: string[] }
/** 会转人工的情况。nodes 是触发它的节点（按优先顺序，取本次真的出现的第一个）。 */
export const HANDOFF_RULES: HandoffRule[] = [
  { key: 'safety', codes: ['safety_review'], name: '风险预检命中', detail: '投诉、12315、曝光或严重不适', nodes: ['safety_gate'] },
  { key: 'agent', codes: ['model_requested', 'customer_requested'], name: 'Agent 判断需人工', detail: '退款、赔偿等超出 AI 权限的诉求', nodes: ['composer'] },
  { key: 'verify', codes: ['invalid_reply'], name: '核验未通过', detail: '修复一次后仍有事实或承诺问题', nodes: ['verifier', 'program_check', 'output_gate'] },
  { key: 'image', codes: ['unsupported_image'], name: '图片需人工', detail: '视觉 Agent 无法判断的图片', nodes: ['vision'] },
  { key: 'timeout', codes: ['reply_timeout'], name: '超过等待时限', detail: '客户等待过久', nodes: [] },
  { key: 'fault', codes: ['generation_failed', 'model_unavailable', 'failed'], name: '模型故障', detail: '生成失败或模型不可用', nodes: [] },
  { key: 'operator', codes: ['operator_takeover'], name: '客服主动接管', detail: '客服在接待台接手', nodes: [] },
]
const HANDOFF_TEXT: Record<string, string> = {
  reply_timeout: '超过等待时限', invalid_reply: '回复未通过核验', safety_review: '安全闸门命中', generation_failed: '生成失败',
  model_unavailable: '模型不可用', unsupported_image: '图片需人工查看', customer_requested: '客户要求人工', operator_takeover: '人工已接管',
  model_requested: 'Agent 判断需要人工', failed: '运行失败',
}
const DRAFT_STATUSES = new Set(['draft', 'needs_review', 'partial'])

/** 从追踪里找出转人工的原因代码：优先人工接续节点记下的 reason_code，旧数据从发送闸门的说明里反查。 */
export function handoffReason(spans: TraceSpan[]): string | null {
  const top = spans.filter((s) => !isModelSpan(s))
  for (const s of top.filter((x) => x.name === 'handoff')) for (const r of s.reasons ?? []) {
    if (r && typeof r === 'object' && 'reason_code' in r) return String((r as { reason_code: unknown }).reason_code)
  }
  const gate = top.filter((s) => s.name === 'send_gate').at(-1)
  const text = [gate?.summary ?? '', ...(gate?.reasons ?? []).map((r) => (typeof r === 'string' ? r : JSON.stringify(r)))].join(' ')
  if (!text.includes('转人工')) return null
  const hit = Object.entries(HANDOFF_TEXT).find(([, v]) => text.includes(v))
  if (hit) return hit[0]
  return text.includes('安全') ? 'safety_review' : 'model_requested'
}

export type Fork = { path: ForkPath; send: OrchCard; handoff: OrchCard; reason: string | null; triggerKey: string | null; rule: HandoffRule | null }

/** 末尾分叉：两条路都画出来，走了哪条点亮哪条；另一条写明为什么没走。 */
export function buildFork(spans: TraceSpan[], rows: OrchRow[], status: string | undefined, outcomeText: string | null | undefined): Fork {
  const top = [...spans].filter((s) => !isModelSpan(s)).sort((a, b) => a.seq - b.seq)
  const sendSpan = top.filter((s) => s.name === 'send_gate').at(-1) ?? null
  const handoffSpan = top.filter((s) => s.name === 'handoff').at(-1) ?? null
  let code = handoffReason(spans)
  if (!code && status === 'handoff') code = 'model_requested'
  if (!code && status === 'failed') code = 'failed'
  const draft = status != null && DRAFT_STATUSES.has(status)
  const path: ForkPath = code ? 'handoff' : status === 'sent' ? 'send' : draft ? 'handoff' : status === 'running' || !status ? 'pending' : 'none'
  const rule = code ? HANDOFF_RULES.find((r) => r.codes.includes(code!)) ?? null : null
  const present = new Map(rows.flatMap((r) => r.cards).map((c) => [c.key, c]))
  const triggerKey = rule?.nodes.find((n) => present.has(n)) ?? null
  if (triggerKey) present.get(triggerKey)!.trigger = true
  const reason = code ? (HANDOFF_TEXT[code] ?? code) : null
  const base = (key: string, label: string, badge: OrchCard['badge'], span: TraceSpan | null): OrchCard => ({
    key, label, role: badge === 'send' ? 'Leader · 收口' : '人工 · 接续', badge, state: 'none', summary: '', checks: [], inputs: [],
    spanId: span?.spanId ?? null, start: 0, end: 0, durationMs: null, model: null, records: span ? 1 : 0, attempts: span ? 1 : 0, issues: 0,
  })
  const send = base('send', 'AI 自动发送', 'send', path === 'send' ? sendSpan : null)
  const handoff = base('handoff', '人工接续', 'human', handoffSpan ?? (path === 'handoff' ? sendSpan : null))
  const triggerLabel = triggerKey ? present.get(triggerKey)!.label : null
  if (path === 'send') {
    send.state = 'ok'
    send.summary = outcomeText || '已自动回复客户'
    send.checks = checksOf(sendSpan)
  } else {
    send.summary = path === 'pending' ? '等待编排结果' : draft && !code ? '草稿模式不自动发送' : path === 'none' ? '本轮被客户新消息取代，未发送' : `未发送：${reason}`
  }
  if (path === 'handoff') {
    handoff.state = 'ok'
    handoff.summary = draft && !code ? '草稿模式：建议回复交给客服审核后发送' : `转人工：${reason}，会话切到人工辅助，等待客服接手`
    if (triggerLabel) handoff.inputs = [{ label: '触发', text: `${triggerLabel} → ${rule?.name ?? reason}` }]
    const own = checksOf(handoffSpan).filter((c) => c.name !== '触发原因')
    handoff.checks = draft && !code ? [] : [
      ...(rule ? [{ name: rule.name, hit: true, detail: rule.detail }] : reason ? [{ name: reason, hit: true, detail: '' }] : []),
      ...own,
    ]
  } else {
    handoff.summary = path === 'pending' ? '满足任一条件即转人工' : '本次未触发转人工'
    handoff.checks = HANDOFF_RULES.filter((r) => r.key !== 'operator').map((r) => ({ name: r.name, hit: false, detail: r.detail }))
  }
  return { path, send, handoff, reason, triggerKey, rule }
}
