/**
 * 大声纹日期（X-1）失败方式：
 * D1 数据跨很多天时柱子细成线（默认应只取最密集的连续 7 天）；
 * D2 窗口按“有数据的 7 个日期”而非日历 7 天取，把相隔很远的日子凑在一起；
 * D3 中间空白日不标断轴，读者误以为相邻。
 */
import { describe, expect, it } from 'vitest'
import { axisBreaks, densestWindow } from './distDays'

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
})
