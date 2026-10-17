/** 对话回放的纯函数（风险页反馈 4）：情绪曲线、节点语义标签、服务轴事件。 */
import type { ServiceScoreView } from '../../api/client'

type Note = ServiceScoreView['notes'][number]
export type Pt = { x: number; y: number }

/** 平滑曲线：Catmull-Rom 转三次贝塞尔，经过每个点；张力 0.5 以内不出现明显过冲。 */
export function smoothPath(points: Pt[], tension = 0.35): string {
  if (!points.length) return ''
  if (points.length === 1) return `M${points[0].x} ${points[0].y}`
  let d = `M${points[0].x} ${points[0].y}`
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] ?? points[i], p1 = points[i], p2 = points[i + 1], p3 = points[i + 2] ?? p2
    const c1 = { x: p1.x + (p2.x - p0.x) * tension / 2, y: p1.y + (p2.y - p0.y) * tension / 2 }
    const c2 = { x: p2.x - (p3.x - p1.x) * tension / 2, y: p2.y - (p3.y - p1.y) * tension / 2 }
    // 控制点纵向夹在两端之间，曲线不会冲出 激烈/平稳 网格线
    const lo = Math.min(p1.y, p2.y), hi = Math.max(p1.y, p2.y)
    c1.y = Math.max(lo, Math.min(hi, c1.y)); c2.y = Math.max(lo, Math.min(hi, c2.y))
    d += ` C${c1.x.toFixed(1)} ${c1.y.toFixed(1)} ${c2.x.toFixed(1)} ${c2.y.toFixed(1)} ${p2.x} ${p2.y}`
  }
  return d
}

const NODE_TAGS: [RegExp, string][] = [
  [/假货|假的|不是正品|山寨|仿冒/, '指责假货'],
  [/举报|12315|曝光|工商|消协|媒体/, '威胁举报'],
  [/投诉|差评/, '投诉'],
  [/过敏|红肿|刺痛|起疹|发痒|烂脸|医院|就医/, '不良反应'],
  [/退款|退钱|退货/, '要求退款'],
  [/人工|真人|客服呢/, '要求人工'],
  [/骗|垃圾|敷衍|什么态度/, '指责服务'],
  [/几天了|还没|怎么还|催|到底/, '催促'],
]

/** 消费者节点上方的具体标签，最多 2 个；平稳且无信号的消息不打标签。 */
export function nodeTags(note: Note): string[] {
  if (note.role !== 'customer') return []
  if (note.level === 'calm' && !(note.signals?.length)) return []
  return NODE_TAGS.filter(([re]) => re.test(note.body)).map(([, tag]) => tag).slice(0, 2)
}

export type ServiceEvent = { messageId: string; x: number; label: string; tone: 'warn' | 'ai' | 'handoff' | 'action' | 'staff' }

const ACTIONS: [RegExp, string][] = [
  [/退货单|退货地址|寄回/, '发送退货单'],
  [/退款.*(?:提交|申请|处理)|(?:提交|申请).*退款/, '提交退款'],
  [/补发|换货/, '补发换货'],
  [/工单/, '建工单'],
  [/物流|快递|单号/, '物流说明'],
]

const fmtWait = (ms: number) => (ms >= 60000 ? `${Math.round(ms / 60000)}m` : `${Math.round(ms / 1000)}s`)

/**
 * 服务轴事件：超时(等待超 2 分钟，标在回复处)、AI安抚(负面消息后的 AI 回复)、转人工(系统提示)、
 * 具体动作(回复里提到的退货单/补发等)、其余人工回复只画点不写字。
 */
export function serviceEvents(score: ServiceScoreView, xOf: Map<string, number>): ServiceEvent[] {
  const out: ServiceEvent[] = []
  const waitTo = new Map(score.waits.filter((w) => w.toMessageId && w.ms > 120000).map((w) => [w.toMessageId!, w.ms]))
  let lastCustomer: Note | undefined
  for (const note of score.notes) {
    const x = xOf.get(note.messageId)
    if (note.role === 'customer') { lastCustomer = note; continue }
    if (x == null && note.role !== 'system') continue
    if (note.role === 'system') {
      if (/转人工|人工客服|已为您转接/.test(note.body) && lastCustomer) {
        out.push({ messageId: note.messageId, x: xOf.get(lastCustomer.messageId) ?? 0, label: '转人工', tone: 'handoff' })
      }
      continue
    }
    const wait = waitTo.get(note.messageId)
    if (wait) out.push({ messageId: `${note.messageId}:wait`, x: x!, label: `超时(${fmtWait(wait)})`, tone: 'warn' })
    const action = ACTIONS.find(([re]) => re.test(note.body))
    if (action) out.push({ messageId: note.messageId, x: x!, label: action[1], tone: 'action' })
    else if (note.role === 'assistant' && lastCustomer && lastCustomer.level && lastCustomer.level !== 'calm') {
      out.push({ messageId: note.messageId, x: x!, label: 'AI安抚', tone: 'ai' })
    } else out.push({ messageId: note.messageId, x: x!, label: '', tone: note.role === 'assistant' ? 'ai' : 'staff' })
  }
  return out
}
