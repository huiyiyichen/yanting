/**
 * 风险页反馈 4 对话回放：
 * C1 曲线是折线或冲出网格；C2 节点无具体标签或平稳消息也打标签；
 * C3 服务轴没有 超时(3m)/AI安抚/转人工/发送退货单 等语义标签。
 */
import { describe, expect, it } from 'vitest'
import type { ServiceScoreView } from '../../api/client'
import { nodeTags, serviceEvents, smoothPath } from './replayModel'

const note = (messageId: string, role: 'customer' | 'operator' | 'assistant' | 'system', body: string, level?: 'calm' | 'dissatisfied' | 'angry') =>
  ({ messageId, role, body, at: '2026-05-01T02:00:00Z', level, signals: [], highlights: [] })

describe('replayModel', () => {
  it('C1 平滑曲线经过各点且控制点不越界', () => {
    const d = smoothPath([{ x: 0, y: 10 }, { x: 30, y: 80 }, { x: 60, y: 10 }])
    expect(d.startsWith('M0 10') && d.includes(' C') && d.endsWith('60 10')).toBe(true)
    const ys = [...d.matchAll(/C[\d.]+ ([\d.]+) [\d.]+ ([\d.]+)/g)].flatMap((m) => [Number(m[1]), Number(m[2])])
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(10); expect(Math.max(...ys)).toBeLessThanOrEqual(80)
  })
  it('C2 节点标签', () => {
    expect(nodeTags(note('a', 'customer', '你们卖假货，我要去12315举报', 'angry'))).toEqual(['指责假货', '威胁举报'])
    expect(nodeTags(note('b', 'customer', '还没到哦', 'calm'))).toEqual([])
  })
  it('C3 服务轴事件', () => {
    const score: ServiceScoreView = {
      conversationId: 'c', breaks: [],
      notes: [note('c1', 'customer', '怎么还没发货', 'angry'), note('a1', 'assistant', '亲，非常理解您着急'),
        note('s1', 'system', '已为您转人工'), note('c2', 'customer', '快点', 'dissatisfied'),
        note('o1', 'operator', '这是退货单，麻烦寄回')],
      waits: [{ fromMessageId: 'c2', toMessageId: 'o1', ms: 180000 }],
    }
    const xOf = new Map([['c1', 10], ['a1', 20], ['c2', 30], ['o1', 40]])
    expect(serviceEvents(score, xOf).filter((e) => e.label).map((e) => e.label))
      .toEqual(['AI安抚', '转人工', '超时(3m)', '发送退货单'])
  })
})
