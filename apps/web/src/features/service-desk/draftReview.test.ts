/**
 * 发送前质检的前端拦截（P1-5）。失败方式：
 * H1 高严重度提示时第一次发送没有被拦下。
 * H2 拦下后再次点击仍被拦（应放行，不能阻断发送）。
 * H3 改动草稿后沿用旧的确认，新问题不再拦。
 * H4 只有中严重度提示时也拦截（只提示，不拦）。
 */
import { describe, expect, it } from 'vitest'
import { shouldHoldSend } from './draftReview'

const high = [{ kind: 'fact_mismatch', severity: 'high', label: '金额与记录不符', quote: '9.80元', start: 0, end: 5 }]
const medium = [{ kind: 'unfounded_promise', severity: 'medium', label: '含无依据承诺', quote: '保证', start: 0, end: 2 }]

describe('shouldHoldSend', () => {
  it('H1 holds the first send with a high finding', () => expect(shouldHoldSend(high, '退款9.80元', null)).toBe(true))
  it('H2 releases the second send of the same draft', () => expect(shouldHoldSend(high, '退款9.80元', '退款9.80元')).toBe(false))
  it('H3 holds again after the draft changed', () => expect(shouldHoldSend(high, '退款9.90元', '退款9.80元')).toBe(true))
  it('H4 never holds for medium findings', () => expect(shouldHoldSend(medium, '保证到', null)).toBe(false))
})
