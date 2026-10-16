/**
 * 全景排序与计时（全景方案 3.4 / 3.9）失败方式：
 * F3 排序随每条新消息抖动（按最后活动排序）。
 * W1 待人工不是等待最久在前；AI 接待中高风险不在前。
 * W2 等待计时格式与阈值（≥120 秒为超时）不一致。
 */
import { describe, expect, it } from 'vitest'
import type { PanoramaItem } from '../../api/client'
import { clock, isLate, laneOrder, matches } from './panoramaModel'

const item = (id: string, patch: Partial<PanoramaItem>): PanoramaItem => ({
  conversationId: id, buyerAlias: id, scene: '', lane: 'ai', emotionBands: [], highRisk: false,
  lastActivityAt: '2026-10-16T10:00:00Z', laneEnteredAt: '2026-10-16T10:00:00Z', ...patch,
} as PanoramaItem)

describe('panoramaModel', () => {
  it('F3 新消息（lastActivityAt 变化）不改变 AI 泳道顺序', () => {
    const a = item('a', { laneEnteredAt: '2026-10-16T10:00:00Z' })
    const b = item('b', { laneEnteredAt: '2026-10-16T10:01:00Z' })
    const before = laneOrder('ai', [a, b]).map((x) => x.conversationId)
    const after = laneOrder('ai', [{ ...a, lastActivityAt: '2026-10-16T10:05:00Z' }, b]).map((x) => x.conversationId)
    expect(after).toEqual(before)
  })
  it('W1 待人工等待最久在前；AI 高风险在前', () => {
    const wait = laneOrder('wait', [
      item('x', { lane: 'wait', waitingSince: '2026-10-16T10:05:00Z' }),
      item('y', { lane: 'wait', waitingSince: '2026-10-16T10:01:00Z' })])
    expect(wait.map((x) => x.conversationId)).toEqual(['y', 'x'])
    const ai = laneOrder('ai', [item('p', {}), item('q', { highRisk: true, laneEnteredAt: '2026-10-16T11:00:00Z' })])
    expect(ai[0].conversationId).toBe('q')
  })
  it('W2 计时与超时筛选', () => {
    const now = Date.parse('2026-10-16T10:02:00Z')
    expect(clock(9)).toBe('0:09')
    expect(clock(3725)).toBe('1:02:05')
    expect(isLate(item('a', { waitingSince: '2026-10-16T10:00:00Z' }), now)).toBe(true)
    expect(matches(item('a', { waitingSince: '2026-10-16T10:01:30Z' }), 'late', now)).toBe(false)
    expect(matches(item('a', { highRisk: true }), 'risk', now)).toBe(true)
  })
})
