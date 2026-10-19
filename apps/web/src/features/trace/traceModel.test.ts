/**
 * Agent 追踪台模型（多 Agent 8.3）失败方式：
 * L1 时序泳道把模型调用当成独立行，而不是父 Agent 条内的金色段；行不按执行顺序。
 * L2 重试的 Agent 没有另起一行标 @2；跳过的节点没写原因；决策不是菱形（无时长）。
 * L3 并行跨度没有标记同组；横轴没有按追踪开始时间对齐。
 * L4 回放顺序与开始时间不一致；倍速不生效。
 * L5 引用链没把同一分段的多个来源归在一起；未核验来源没有标出。
 */
import { describe, expect, it } from 'vitest'
import { buildLanes, buildOrchestration, cardStateText, citationChain, replayFrames } from './traceModel'

const t = (ms: number) => new Date(Date.parse('2026-05-01T00:00:00Z') + ms).toISOString()
const span = (o: Record<string, unknown>) => ({ parentSpanId: null, attempt: 1, parallelGroup: null, status: 'ok', label: '', reasons: [], kind: 'agent', ...o })
const spans = [
  span({ spanId: 'a', seq: 0, kind: 'decision', name: 'safety_gate', startedAt: t(0), endedAt: t(5), durationMs: 5 }),
  span({ spanId: 'b', seq: 1, name: 'trajectory', parallelGroup: 'fanout', startedAt: t(10), endedAt: t(300), durationMs: 290 }),
  span({ spanId: 'c', seq: 2, name: 'knowledge', parallelGroup: 'fanout', startedAt: t(10), endedAt: t(800), durationMs: 790 }),
  span({ spanId: 'c1', seq: 3, kind: 'model', parentSpanId: 'c', name: 'knowledge', startedAt: t(100), endedAt: t(700), durationMs: 600 }),
  span({ spanId: 'v', seq: 4, name: 'vision', status: 'skipped', reasons: ['无图片'], startedAt: t(10), endedAt: t(10), durationMs: 0 }),
  span({ spanId: 'd1', seq: 5, name: 'composer', status: 'failed', startedAt: t(800), endedAt: t(1800), durationMs: 1000 }),
  span({ spanId: 'd2', seq: 6, name: 'composer', attempt: 2, startedAt: t(1800), endedAt: t(2600), durationMs: 800 }),
]

describe('traceModel', () => {
  it('L1 L2 L3 泳道', () => {
    const { rows, total } = buildLanes(t(0), spans as never)
    expect(rows.map((r) => r.label)).toEqual(['安全闸门', '轨迹查询', '知识', '视觉', '共情起草', '共情起草 @2'])
    expect(rows[2].models).toEqual([{ start: 100, end: 700, spanId: 'c1' }])
    expect(rows[0].kind).toBe('decision')
    expect(rows[3].status).toBe('skipped'); expect(rows[3].note).toBe('无图片')
    expect(rows[1].group).toBe('fanout'); expect(rows[1].start).toBe(10)
    expect(total).toBe(2600)
  })
  it('L4 回放', () => {
    const frames = replayFrames(buildLanes(t(0), spans as never).rows, 4)
    expect(frames.map((f) => f.spanId)).toEqual(['a', 'b', 'c', 'v', 'd1', 'd2'])
    expect(frames[4].delay).toBe(198)
  })
  it('L5 引用链', () => {
    const chain = citationChain([
      { replyStyle: 'recommended', segmentIndex: 1, segmentText: '售后在处理', sourceId: 'ticket:K1', sheetName: '售后表', rowNumber: 12, verdict: 'verified' },
      { replyStyle: 'recommended', segmentIndex: 2, segmentText: '退款8.8元', sourceId: 'order:O1', sheetName: '订单表', rowNumber: 5, verdict: 'verified' },
      { replyStyle: 'recommended', segmentIndex: 2, segmentText: '退款8.8元', sourceId: 'msg:S5#4', sheetName: null, rowNumber: null, verdict: 'unverified' },
    ] as never)
    expect(chain.map((c) => [c.index, c.sources.length])).toEqual([[1, 1], [2, 2]])
    expect(chain[1].sources[1].ok).toBe(false)
  })

  it('O5 闸门逐项检查从 reasons.checks 读出', () => {
    const gate = span({ spanId: 'g', seq: 0, kind: 'decision', name: 'safety_gate', summary: '2 项检查均未触发', startedAt: t(0), endedAt: t(1), durationMs: 1,
      reasons: [{ checks: [{ name: '投诉 / 维权', hit: false, detail: '未出现投诉' }, { name: '就医 / 严重不良反应', hit: true, detail: '命中“脸肿”' }] }] })
    const card = buildOrchestration(t(0), [gate] as never).rows[0].cards[0]
    expect(card.checks.map((c) => c.hit)).toEqual([false, true]); expect(card.badge).toBe('gate')
  })
  it('O1–O4 编排卡片树：并行分支成行、重试合并、模型调用（model_call）归到卡片、一句话产出', () => {
    const more = [...spans,
      span({ spanId: 'd2m', seq: 7, kind: 'model_call', parentSpanId: 'd2', name: 'composer', startedAt: t(1900), endedAt: t(2500), durationMs: 600, modelReturned: 'qwen-plus' }),
      span({ spanId: 'p', seq: 8, kind: 'gate', name: 'program_check', summary: '程序核验通过', startedAt: t(2600), endedAt: t(2610), durationMs: 10 }),
    ]
    ;(more[5] as Record<string, unknown>).summary = '草稿 86 字'
    ;(more[6] as Record<string, unknown>).summary = '草稿 90 字 · 第 2 次起草'
    const { rows } = buildOrchestration(t(0), more as never)
    expect(rows.map((r) => r.key)).toEqual(['gate', 'workers', 'compose', 'checks'])
    const workers = rows[1]
    expect(workers.fan).toBe(true)
    // 反馈 10-19 #4：没运行/跳过的节点不占位
    expect(workers.cards.map((c) => c.label)).toEqual(['轨迹查询', '知识'])
    expect(workers.title).toBe('并行调用 2 个 Worker')
    expect(cardStateText(workers.cards[0])).toBe('已返回结果')
    const composer = rows[2].cards[0]
    expect(composer.attempts).toBe(2); expect(composer.state).toBe('ok'); expect(composer.spanId).toBe('d2')
    expect(composer.summary).toBe('草稿 90 字 · 第 2 次起草')
    expect(composer.model).toBe('qwen-plus'); expect(composer.durationMs).toBe(1800)
    expect(rows[3].cards.map((c) => [c.label, c.state])).toEqual([['程序核验', 'ok']])
    expect(rows[3].fan).toBe(false)
    expect(composer.inputs.map((i) => i.label)).toEqual(['轨迹查询', '知识'])
    expect(composer.badge).toBe('leader'); expect(workers.cards[0].badge).toBe('worker')
    expect(buildLanes(t(0), more as never).rows.find((r) => r.spanId === 'd2')!.models).toHaveLength(1)
  })
})

describe('修复回路（阶段 5）', () => {
  // R1 起草出现两次却没标出修复回路；R2 回路起点不是打回草稿的那道核验；R3 没有重试时也画回路
  const loop = [
    span({ spanId: 'k', seq: 0, name: 'composer', startedAt: t(0), endedAt: t(900), durationMs: 900 }),
    span({ spanId: 'p', seq: 1, name: 'program_check', startedAt: t(900), endedAt: t(910), durationMs: 10 }),
    span({ spanId: 'q', seq: 2, name: 'verifier', status: 'ok', reasons: ['回复的说法没有来源支持'], startedAt: t(910), endedAt: t(1500), durationMs: 590 }),
    span({ spanId: 'k2', seq: 3, name: 'composer', attempt: 2, startedAt: t(1500), endedAt: t(2300), durationMs: 800 }),
    span({ spanId: 'p2', seq: 4, name: 'program_check', startedAt: t(2300), endedAt: t(2310), durationMs: 10 }),
  ]
  it('R1 R2 marks the loop from the verifier back to the composer', () => {
    const { repair } = buildOrchestration(t(0), loop as never)
    expect(repair).toEqual({ from: '核验', fromKey: 'verifier', reason: '回复的说法没有来源支持', attempts: 2, spanId: 'q' })
  })
  it('R3 no loop without a retry', () => {
    expect(buildOrchestration(t(0), loop.slice(0, 3) as never).repair).toBeNull()
  })
})

describe('意图情绪 Agent', () => {
  it('U5 与取证 Worker 同排显示为 Worker · 理解', () => {
    const s = [
      span({ spanId: 't', seq: 0, name: 'triage', startedAt: t(0), endedAt: t(5), durationMs: 5 }),
      span({ spanId: 'j', seq: 1, name: 'trajectory', parallelGroup: 'evidence', startedAt: t(5), endedAt: t(300), durationMs: 295 }),
      span({ spanId: 'u', seq: 2, name: 'understand', parallelGroup: 'evidence', startedAt: t(5), endedAt: t(200), durationMs: 195 }),
      span({ spanId: 'k', seq: 3, name: 'composer', startedAt: t(300), endedAt: t(900), durationMs: 600 }),
    ]
    const workers = buildOrchestration(t(0), s as never).rows.find((r) => r.key === 'workers')!
    expect(workers.cards.map((c) => c.label)).toEqual(['轨迹查询', '意图情绪'])
    expect(workers.cards[1].role).toBe('Worker · 理解')
    expect(workers.title).toBe('并行调用 2 个 Worker')
  })
})
