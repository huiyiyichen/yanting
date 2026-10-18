/**
 * Agent 追踪台模型（多 Agent 8.3）失败方式：
 * L1 时序泳道把模型调用当成独立行，而不是父 Agent 条内的金色段；行不按执行顺序。
 * L2 重试的 Agent 没有另起一行标 @2；跳过的节点没写原因；决策不是菱形（无时长）。
 * L3 并行跨度没有标记同组；横轴没有按追踪开始时间对齐。
 * L4 回放顺序与开始时间不一致；倍速不生效。
 * L5 引用链没把同一分段的多个来源归在一起；未核验来源没有标出。
 */
import { describe, expect, it } from 'vitest'
import { buildLanes, citationChain, replayFrames } from './traceModel'

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
})
