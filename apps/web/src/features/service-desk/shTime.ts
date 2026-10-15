/**
 * 统一时间：带 Z/偏移的按北京时间显示；无时区的源数据本身就是北京时间，原样取。
 * 排序时把无时区值按 +08:00 解析，避免和带时区的值混排错位。
 */
const ZONED = /(Z|[+-]\d{2}:?\d{2})$/
const fmt = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })

function parts(value?: string | null) {
  if (!value) return null
  const v = value.trim().replace(' ', 'T')
  if (ZONED.test(v)) {
    const d = new Date(v)
    if (Number.isNaN(d.getTime())) return null
    const p = Object.fromEntries(fmt.formatToParts(d).map((x) => [x.type, x.value]))
    return { m: p.month, d: p.day, hm: `${p.hour === '24' ? '00' : p.hour}:${p.minute}` }
  }
  const m = v.match(/^\d{4}-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/)
  return m ? { m: m[1], d: m[2], hm: m[3] ? `${m[3]}:${m[4]}` : '' } : null
}
export const shMonthDay = (value?: string | null) => { const p = parts(value); return p ? `${p.m}/${p.d}` : '' }
export const shHourMinute = (value?: string | null) => parts(value)?.hm ?? ''
export const shTimestamp = (value?: string | null) => {
  if (!value) return 0
  const v = value.trim().replace(' ', 'T')
  return Date.parse(ZONED.test(v) ? v : `${v}+08:00`) || 0
}
