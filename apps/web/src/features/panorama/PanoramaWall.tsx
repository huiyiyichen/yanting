import { useLayoutEffect, useRef } from 'react'
import type { PanoramaItem } from '../../api/client'
import { PanoramaTile } from './PanoramaTile'
import { LANE_LABEL, clock, laneOrder, matches, waitSeconds, type Lane, type PanoramaFilter } from './panoramaModel'

const EASE = 'cubic-bezier(.2,.8,.2,1)'
const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

/** 墙面：上排待人工、人工处理中，下排 AI 接待中；换泳道用 FLIP 位移。 */
export function PanoramaWall({ items, now, filter, selectedId, running, queued, windowMinutes, onSelect }: {
  items: PanoramaItem[]
  now: number
  filter: PanoramaFilter
  selectedId: string | null
  running: number
  queued: number
  /** 全景只看最近 N 分钟有动静的会话；为空时用来解释"为什么墙上是空的"。 */
  windowMinutes?: number
  onSelect: (id: string) => void
}) {
  const host = useRef<HTMLDivElement>(null)
  const last = useRef(new Map<string, DOMRect>())
  const layoutKey = (['wait', 'human', 'ai'] as Lane[]).map((lane) => laneOrder(lane, items).map((i) => i.conversationId).join(',')).join('|')
  useLayoutEffect(() => {
    const tiles = host.current?.querySelectorAll<HTMLElement>('.yt-ptile') ?? []
    const next = new Map<string, DOMRect>()
    tiles.forEach((el) => {
      const id = el.dataset.id ?? ''
      const rect = el.getBoundingClientRect()
      next.set(id, rect)
      if (reduced() || !el.animate) return
      const prev = last.current.get(id)
      if (!prev) {
        if (last.current.size) el.animate([{ opacity: 0, transform: 'scale(.6)' }, { opacity: 1, transform: 'none' }], { duration: 420, easing: EASE })
        return
      }
      const dx = prev.left - rect.left
      const dy = prev.top - rect.top
      if (Math.abs(dx) + Math.abs(dy) > 1) el.animate([{ transform: `translate(${dx}px,${dy}px)` }, { transform: 'none' }], { duration: 560, easing: EASE })
    })
    last.current = next
  }, [layoutKey])
  const lane = (key: Lane) => {
    const list = laneOrder(key, items)
    const longest = key === 'wait' ? Math.max(0, ...list.map((item) => waitSeconds(item, now) ?? 0)) : 0
    return <section className={`yt-plane is-${key}`} aria-label={LANE_LABEL[key]}>
      <header className="yt-plane-head"><strong>{LANE_LABEL[key]}</strong><span className="yt-plane-n">{list.length}</span>
        {key === 'wait' && list.length > 0 && <span className="yt-plane-sub">最长等待 <em>{clock(longest)}</em></span>}
        {key === 'ai' && <span className="yt-plane-sub">处理中 <em>{running}</em> &nbsp;排队 <em>{queued}</em></span>}
      </header>
      <div className="yt-plane-tiles">{list.map((item) => <PanoramaTile key={item.conversationId} item={item} now={now}
        selected={item.conversationId === selectedId} dimmed={!matches(item, filter, now)} onSelect={onSelect} />)}</div>
    </section>
  }
  return <div className="yt-pwall" ref={host}>
    {items.length === 0 &&
      <div className="yt-pwall-empty" role="status">
        <strong>最近 {windowMinutes ?? 120} 分钟没有正在进行的会话</strong>
        <span>全景只显示近期有活动的接待会话；左侧队列里的历史会话仍可正常打开。</span>
      </div>}
    <div className="yt-pwall-top">{lane('wait')}{lane('human')}</div>
    {lane('ai')}
  </div>
}
