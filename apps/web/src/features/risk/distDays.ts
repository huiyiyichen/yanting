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
