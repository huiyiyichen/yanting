import { memo, useEffect, useRef } from 'react'

export type SwatchLevel = 'calm' | 'dissatisfied' | 'angry'
export const SWATCH_LABEL: Record<SwatchLevel, string> = { calm: '平稳', dissatisfied: '不满', angry: '激烈' }
const COLOR: Record<SwatchLevel, string> = { calm: 'var(--yt-calm)', dissatisfied: 'var(--yt-upset)', angry: 'var(--yt-fury)' }

/** 尺寸：宽、高、斜切差、段间隔、最多段数（全景方案 2.1）。 */
const SIZES = {
  lg: { w: 40, h: 66, cut: 9, gap: 2, max: 6 },
  md: { w: 32, h: 54, cut: 7, gap: 1.5, max: 6 },
  sm: { w: 12, h: 20, cut: 3, gap: 1, max: 6 },
} as const

/** 每段高度：一段占满；多段时最新一段 40%，其余平分 60%。 */
export function bandHeights(count: number, height: number, gap: number): number[] {
  if (count <= 0) return []
  const inner = height - gap * (count - 1)
  if (count === 1) return [inner]
  return [...Array<number>(count - 1).fill((inner * 0.6) / (count - 1)), inner * 0.4]
}

const clip = (w: number, h: number, cut: number) => {
  const r = Math.min(5, w / 2.4)
  return `path('M0 ${cut} L${w} 0 L${w} ${h - r} Q${w} ${h} ${w - r} ${h} L${r} ${h} Q0 ${h} 0 ${h - r} Z')`
}

/** 情绪色号：单会话的消费者情绪，每条消息一段色带，时间从上往下，最新一段加高。 */
export const EmotionSwatch = memo(function EmotionSwatch({ bands, highRisk = false, size = 'md' }: {
  bands: SwatchLevel[]
  highRisk?: boolean
  size?: keyof typeof SIZES
}) {
  const spec = SIZES[size]
  const shown = bands.slice(-spec.max)
  const heights = bandHeights(shown.length, spec.h, spec.gap)
  const label = `${shown.length ? shown.map((level) => SWATCH_LABEL[level]).join('、') : '暂无消费者消息'}${highRisk ? '，高风险' : ''}`
  const lastRef = useRef<HTMLSpanElement>(null)
  const seen = useRef(shown.length)
  useEffect(() => {
    if (shown.length > seen.current && lastRef.current?.animate
      && !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      lastRef.current.animate([{ transform: 'scaleY(0)' }, { transform: 'scaleY(1)' }], { duration: 420, easing: 'cubic-bezier(.2,.8,.2,1)' })
    }
    seen.current = shown.length
  }, [shown.length])
  return <span className={`yt-swatch is-${size}`} role="img" aria-label={label} style={{ width: spec.w, height: spec.h }}>
    <span className="yt-swatch-body" style={{ gap: spec.gap, clipPath: clip(spec.w, spec.h, spec.cut) }}>
      {shown.map((level, i) => <span key={i} ref={i === shown.length - 1 ? lastRef : undefined}
        className={`yt-swatch-band is-${level}`} style={{ height: heights[i], background: COLOR[level] }} />)}
    </span>
    {highRisk && <span className="yt-swatch-risk" aria-hidden="true" />}
  </span>
})
