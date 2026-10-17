/** 大声纹的日期取舍（全景方案 X-1）：默认只看最密集的连续 7 天；相邻有数据的日期间隔超过 1 天时断轴。 */
type Bucket = { date: string; calm: number; dissatisfied: number; angry: number }

const dayNo = (date: string) => Math.round(Date.parse(`${date}T00:00:00Z`) / 86400000)

export function densestWindow(buckets: Bucket[], span = 7): string[] {
  const totals = new Map<string, number>()
  for (const b of buckets) totals.set(b.date, (totals.get(b.date) ?? 0) + b.calm + b.dissatisfied + b.angry)
  const days = [...totals.keys()].sort()
  if (!days.length || dayNo(days[days.length - 1]) - dayNo(days[0]) < span) return days
  let best: string[] = [], bestSum = -1
  for (let i = 0; i < days.length; i += 1) {
    const end = dayNo(days[i]) + span - 1
    const inWindow = days.slice(i).filter((d) => dayNo(d) <= end)
    const sum = inWindow.reduce((s, d) => s + (totals.get(d) ?? 0), 0)
    if (sum > bestSum) { best = inWindow; bestSum = sum }
  }
  return best
}

/** 返回需要画断轴的日期下标：该日与前一个有数据的日期之间隔了至少一天空白。 */
export function axisBreaks(days: string[]): Set<number> {
  const breaks = new Set<number>()
  days.forEach((d, i) => { if (i > 0 && dayNo(d) - dayNo(days[i - 1]) > 1) breaks.add(i) })
  return breaks
}

/** 缩略条点某一天：以该天为起点取连续日历 span 天内有数据的日期；越过末尾时整体前移。 */
export function windowFrom(buckets: Bucket[], start: string, span = 7): string[] {
  const days = [...new Set(buckets.map((b) => b.date))].sort()
  if (!days.length) return []
  const last = dayNo(days[days.length - 1])
  const s0 = Math.max(dayNo(days[0]), Math.min(dayNo(start), last - span + 1))
  return days.filter((d) => dayNo(d) >= s0 && dayNo(d) < s0 + span)
}

/** 缩略条数据：每天负面条数（不满+激烈）与总数。 */
export function dailyTotals(buckets: Bucket[]): { date: string; negative: number; total: number }[] {
  const map = new Map<string, { date: string; negative: number; total: number }>()
  for (const b of buckets) {
    const row = map.get(b.date) ?? { date: b.date, negative: 0, total: 0 }
    row.negative += b.dissatisfied + b.angry; row.total += b.calm + b.dissatisfied + b.angry
    map.set(b.date, row)
  }
  return [...map.values()].sort((a, b) => a.date.localeCompare(b.date))
}

/** 区间内有数据的日期。 */
export function daysIn(days: string[], range: { from: string; to: string }): string[] {
  return days.filter((d) => d >= range.from && d <= range.to)
}

const dayStr = (n: number) => new Date(n * 86400000).toISOString().slice(0, 10)

/** 缩略条方向键：区间整体平移 n 个日历天，不越过数据首尾。 */
export function shiftRange(days: string[], range: { from: string; to: string }, n: number): { from: string; to: string } {
  if (!days.length) return range
  const span = dayNo(range.to) - dayNo(range.from)
  const lo = dayNo(days[0]), hi = dayNo(days[days.length - 1])
  const start = Math.max(lo, Math.min(dayNo(range.from) + n, hi - span))
  return { from: dayStr(start), to: dayStr(Math.min(hi, start + span)) }
}
