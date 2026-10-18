import type { MessageView, PanoramaItem, PanoramaView } from '../../api/client'
import sessions from './demoSessions.json'

/**
 * 接待全景演示：按示例稿的节奏回放官方虚构业务数据里的真实会话（顺序不改），
 * 只在前端运行，不写库、不调模型。情绪为项目规则口径（0 平稳 1 不满 2 激烈）。
 */
type Raw = { r: 'c' | 'o'; x: string; lv?: number; by?: string; cf?: boolean; med?: boolean }
type Session = { id: string; alias: string; scene: string; product: string | null; high: string[]; msgs: Raw[] }
type Shown = { role: MessageView['senderRole']; body: string; at: number; lv?: number }
type Step = NonNullable<NonNullable<PanoramaItem['currentRun']>['steps']>[number]
type Run = { mode: 'reply' | 'handoff'; phases: Step[][]; i: number; el: number }
type Conv = {
  s: Session; pos: number; shown: Shown[]; lane: PanoramaItem['lane']; handler: string | null; official: string
  reason: string | null; quote: string | null; waitSince: number | null; run: Run | null; queued: Run['mode'] | null
  lastRun: Run | null; lastAt: number; enteredAt: number; fast: boolean; ending: boolean; seq: number
}

const DATA = sessions as Session[]
const BANDS = ['calm', 'dissatisfied', 'angry'] as const
const MAX_RUNS = 4
/** 多 Agent：分诊 → 情绪风险 ∥ 订单查询 ∥ 知识检索 → 起草 → 核验 → 发送；每项耗时取区间随机值。 */
const PHASES: [string, number, number][][] = [
  [['分诊', 200, 400]],
  [['情绪风险', 300, 700], ['订单查询', 400, 1000], ['知识检索', 500, 1200]],
  [['起草', 1800, 3200]], [['核验', 900, 1800]], [['发送', 200, 300]],
]

export class PanoramaDemo {
  private T = 0
  private readonly start: number
  private events: { at: number; fn: () => void }[] = []
  private convs = new Map<string, Conv>()
  private byId = new Map(DATA.map((d) => [d.id, d]))
  private pool = ['S00058', 'S00049', 'S00113', 'S00141', 'S00026']
  private recycled: string[] = []
  private active = 0
  private seq = 0
  constructor(private readonly rnd: () => number = Math.random, start = Date.now()) {
    this.start = start
    const seed: [string, number, Partial<{ fast: boolean; ago: number }>?][] = [
      ['S00059', 2, { fast: true, ago: 70 }], ['S00014', 1, { ago: 5 }], ['S00002', 2], ['S00092', 3], ['S00117', 3], ['S00030', 2],
      ['S00134', 2], ['S00057', 3], ['S00062', 3], ['S00043', 3], ['S00007', 3], ['S00003', 3], ['S00041', 3], ['S00158', 2], ['S00009', 2],
    ]
    seed.forEach(([id, n, o]) => this.make(id, 'ai', n, o))
    this.make('S00015', 'wait', 1, { reason: '就医 · 安全转人工', ago: 95 })
    this.make('S00044', 'wait', 4, { reason: '核验未通过', ago: 40, kind: 'assistant' })
    this.make('S00004', 'human', 2, { handler: '测试客服' })
    this.make('S00076', 'human', 4, { handler: '欣欣' })
    this.make('S00034', 'human', 3, { handler: '测试客服', ago: 20 })
    this.make('S00087', 'human', 4, { handler: '欣欣' })
    for (const c of this.convs.values()) {
      const last = c.shown.at(-1)
      if (c.lane === 'wait') this.at(c.s.id === 'S00015' ? 35000 : 55000, () => this.takeover(c.s.id, c.official))
      else if (c.lane === 'ai' && last?.role === 'customer') this.at(600, () => this.enqueue(c, 'reply'))
      else if (c.lane === 'human' && last?.role === 'customer') this.at(this.r(3000, 6000), () => this.reply(c, 'operator'))
      else this.at(c.s.id === 'S00059' ? 1200 : this.r(5000, 30000), () => this.next(c))
    }
    this.at(4000, () => this.arrive())
  }

  /** 推进 dt 毫秒（演示暂停时不调用）。 */
  tick(dt: number) {
    this.T += dt
    const due = this.events.filter((e) => e.at <= this.T).sort((a, b) => a.at - b.at)
    this.events = this.events.filter((e) => e.at > this.T)
    due.forEach((e) => e.fn())
    for (const c of this.convs.values()) {
      const run = c.run
      if (!run) continue
      run.el += dt
      while (run.i < run.phases.length) {
        const phase = run.phases[run.i]
        const need = Math.max(...phase.map((s) => s.durationMs))
        phase.forEach((s) => { if (s.status === 'active' && run.el >= s.durationMs) s.status = run.mode === 'handoff' ? 'fail' : 'done' })
        if (run.el < need) break
        run.el -= need
        run.i++
        run.phases[run.i]?.forEach((s) => { s.status = 'active' })
      }
      if (run.i >= run.phases.length) {
        c.lastRun = run; c.run = null; this.active--
        if (run.mode === 'reply') this.reply(c, 'assistant'); else this.handoff(c)
        this.pump()
      }
    }
  }

  /** 演示时钟：所有时间戳都从这里取，暂停时等待计时也停。 */
  now() { return this.start + this.T }

  view(): PanoramaView {
    const items = [...this.convs.values()].filter((c) => !c.ending).map((c) => this.item(c))
    return { items, running: items.filter((i) => i.aiJob === 'running').length, queued: items.filter((i) => i.aiJob === 'queued').length, activeWindowMinutes: 120 }
  }

  messages(id: string): MessageView[] {
    const c = this.convs.get(id)
    if (!c) return []
    return c.shown.map((m, i) => ({
      messageId: `${id}-${i}`, conversationId: id, senderRole: m.role, body: m.body, messageRevision: 1,
      attachments: [], createdAt: this.iso(m.at),
    }) as MessageView)
  }

  takeover(id: string, who = 'G001') {
    const c = this.convs.get(id)
    if (!c || c.lane === 'human') return
    if (c.run) { c.run = null; this.active-- }
    c.queued = null
    c.lane = 'human'; c.handler = who; c.reason = null; c.seq = this.seq++; c.enteredAt = this.T
    this.push(c, 'system', `${who} 已接管`)
    if (c.waitSince != null) this.at(this.r(4000, 7000), () => this.reply(c, 'operator'))
    else this.at(this.r(6000, 12000), () => this.next(c))
    this.pump()
  }

  private r(a: number, b: number) { return a + this.rnd() * (b - a) }
  private at(delay: number, fn: () => void) { this.events.push({ at: this.T + delay, fn }) }
  private iso(t: number) { return new Date(this.start + t).toISOString() }
  private push(c: Conv, role: Shown['role'], body: string, lv?: number) { c.shown.push({ role, body, at: this.T, lv }); c.lastAt = this.T }

  private make(id: string, lane: Conv['lane'], shown: number, opt: Partial<{ fast: boolean; ago: number; handler: string; reason: string; kind: Shown['role'] }> = {}) {
    const s = this.byId.get(id)
    if (!s) return
    const c: Conv = {
      s, pos: 0, shown: [], lane, handler: opt.handler ?? null, official: s.msgs.find((m) => m.r === 'o')?.by ?? '欣欣',
      reason: opt.reason ?? null, quote: null, waitSince: null, run: null, queued: null, lastRun: null,
      lastAt: this.T, enteredAt: this.T, fast: Boolean(opt.fast), ending: false, seq: this.seq++,
    }
    const kind = opt.kind ?? (lane === 'ai' ? 'assistant' : 'operator')
    let t = this.T - (opt.ago ?? this.r(60, 300)) * 1000 - Math.max(0, shown - 1) * 55000
    c.enteredAt = t
    for (let i = 0; i < shown && c.pos < s.msgs.length; i++, t += 55000) {
      const m = s.msgs[c.pos++]
      c.shown.push(m.r === 'c' ? { role: 'customer', body: m.x, lv: m.lv ?? 0, at: t } : { role: kind, body: m.x, at: t })
    }
    const last = c.shown.at(-1)
    if (last) c.lastAt = last.at
    if (last?.role === 'customer') c.waitSince = last.at
    if (lane === 'wait') c.quote = this.lastCustomer(c)?.body ?? null
    this.convs.set(id, c)
    return c
  }

  private lastCustomer(c: Conv) { return [...c.shown].reverse().find((m) => m.role === 'customer') }

  private next(c: Conv) {
    if (!this.convs.has(c.s.id) || c.lane === 'wait' || c.ending) return
    if (c.pos >= c.s.msgs.length) return this.end(c)
    const m = c.s.msgs[c.pos]
    if (m.r !== 'c') return this.reply(c, c.lane === 'ai' ? 'assistant' : 'operator')
    c.pos++
    this.push(c, 'customer', m.x, m.lv ?? 0)
    c.waitSince = this.T
    if (c.lane === 'ai') this.enqueue(c, m.lv === 2 || m.cf || m.med ? 'handoff' : 'reply')
    else this.at(this.r(3500, 7000), () => this.reply(c, 'operator'))
  }

  private reply(c: Conv, role: Shown['role']) {
    if (!this.convs.has(c.s.id)) return
    let n = 0
    while (c.pos < c.s.msgs.length && c.s.msgs[c.pos].r === 'o') { this.push(c, role, c.s.msgs[c.pos++].x); n++ }
    if (!n) return
    c.waitSince = null
    if (c.pos >= c.s.msgs.length) this.at(this.r(7000, 11000), () => this.end(c))
    else this.at(c.fast ? this.r(5000, 7000) : this.r(6000, 16000), () => this.next(c))
  }

  private enqueue(c: Conv, mode: Run['mode']) { c.queued = mode; this.pump() }

  private pump() {
    const waiting = [...this.convs.values()].filter((c) => c.queued && c.lane === 'ai').sort((a, b) => (a.waitSince ?? 0) - (b.waitSince ?? 0))
    for (const c of waiting) {
      if (this.active >= MAX_RUNS) break
      const mode = c.queued as Run['mode']
      c.queued = null; this.active++
      const phases: Step[][] = mode === 'handoff'
        ? [[{ name: '分诊', status: 'active', durationMs: 900, group: null, attempts: 1 }]]
        : PHASES.map((phase, i) => phase.map(([name, a, b]) => ({
          name, status: i ? 'pending' : 'active', durationMs: Math.round(this.r(a, b)), group: phase.length > 1 ? `p${i}` : null, attempts: 1,
        } as Step)))
      c.run = { mode, phases, i: 0, el: 0 }
    }
  }

  private handoff(c: Conv) {
    const src = c.s.msgs[c.pos - 1] ?? ({} as Raw)
    c.lane = 'wait'; c.seq = this.seq++; c.enteredAt = this.T
    c.reason = src.med ? '就医 · 安全转人工' : src.cf || c.s.high.includes('complaint_risk') ? '投诉风险' : '情绪激烈'
    c.quote = this.lastCustomer(c)?.body ?? null
    this.push(c, 'system', '已转人工，客服将继续跟进。')
    this.at(45000, () => { if (c.lane === 'wait') this.takeover(c.s.id, c.official) })
  }

  private end(c: Conv) {
    if (!this.convs.has(c.s.id) || c.ending || c.lane === 'wait') return
    this.convs.delete(c.s.id); this.recycled.push(c.s.id)
  }

  private arrive() {
    const id = this.pool.shift() ?? this.recycled.shift()
    if (id && !this.convs.has(id)) { const c = this.make(id, 'ai', 0, { ago: 0 }); if (c) this.next(c) }
    this.at(this.r(11000, 16000), () => this.arrive())
  }

  private item(c: Conv): PanoramaItem {
    const bands = c.shown.filter((m) => m.role === 'customer').map((m) => BANDS[m.lv ?? 0])
    const steps = (run: Run) => run.phases.flat()
    return {
      conversationId: c.s.id, buyerAlias: c.s.alias, scene: c.s.scene, productName: c.s.product, lane: c.lane, handler: c.handler,
      emotionBands: bands.slice(-6), highRisk: c.s.high.length > 0 || bands.at(-1) === 'angry',
      waitingSince: c.waitSince == null ? null : this.iso(c.waitSince), handoffReason: c.lane === 'wait' ? c.reason : null,
      handoffQuote: c.lane === 'wait' ? c.quote : null, aiJob: c.run ? 'running' : c.queued ? 'queued' : null,
      currentRun: c.run ? { outcome: null, steps: steps(c.run), traceId: null } : null,
      lastRun: c.lastRun ? { outcome: c.lastRun.mode === 'reply' ? 'sent' : 'handoff', steps: steps(c.lastRun), traceId: null } : null,
      lastActivityAt: this.iso(c.lastAt), laneEnteredAt: this.iso(c.enteredAt),
    }
  }
}
