/**
 * 大声纹日期（X-1）失败方式：
 * D1 数据跨很多天时柱子细成线（默认应只取最密集的连续 7 天）；
 * D2 窗口按“有数据的 7 个日期”而非日历 7 天取，把相隔很远的日子凑在一起；
 * D3 中间空白日不标断轴，读者误以为相邻。
 */
import { describe, expect, it } from 'vitest'
import { axisBreaks, dailyTotals, daysIn, densestWindow, shiftRange, windowFrom } from './distDays'

const b = (date: string, n: number) => ({ date, calm: n, dissatisfied: 0, angry: 0 })

describe('distDays', () => {
  it('D1/D2 取日历上最密集的连续 7 天', () => {
    const buckets = [b('2026-05-01', 1), b('2026-05-03', 1), b('2026-05-10', 9), b('2026-05-12', 9), b('2026-05-16', 9), b('2026-05-17', 1), b('2026-05-30', 2)]
    expect(densestWindow(buckets)).toEqual(['2026-05-10', '2026-05-12', '2026-05-16'])
  })
  it('日历跨度不足 7 天全部保留', () => {
    expect(densestWindow([b('2026-05-01', 1), b('2026-05-06', 1)])).toEqual(['2026-05-01', '2026-05-06'])
  })
  it('D3 间隔超过 1 天标断轴', () => {
    expect([...axisBreaks(['2026-05-10', '2026-05-11', '2026-05-14'])]).toEqual([2])
  })
  it('缩略条点某天：从该天起取 7 个日历天，越过末尾时前移', () => {
    const bs = ['2026-05-01', '2026-05-02', '2026-05-05', '2026-05-09', '2026-05-12'].map((date) => ({ date, calm: 1, dissatisfied: 1, angry: 0 }))
    expect(windowFrom(bs, '2026-05-02')).toEqual(['2026-05-02', '2026-05-05'])
    expect(windowFrom(bs, '2026-05-12')).toEqual(['2026-05-09', '2026-05-12'])
    expect(dailyTotals(bs)[0]).toEqual({ date: '2026-05-01', negative: 1, total: 2 })
  })
  it('区间平移不越过数据首尾；daysIn 只取区间内日期', () => {
    const days = ['2026-05-01', '2026-05-03', '2026-05-10']
    expect(shiftRange(days, { from: '2026-05-01', to: '2026-05-03' }, 1)).toEqual({ from: '2026-05-02', to: '2026-05-04' })
    expect(shiftRange(days, { from: '2026-05-01', to: '2026-05-03' }, -3)).toEqual({ from: '2026-05-01', to: '2026-05-03' })
    expect(shiftRange(days, { from: '2026-05-01', to: '2026-05-03' }, 30)).toEqual({ from: '2026-05-08', to: '2026-05-10' })
    expect(daysIn(days, { from: '2026-05-02', to: '2026-05-10' })).toEqual(['2026-05-03', '2026-05-10'])
  })
})

