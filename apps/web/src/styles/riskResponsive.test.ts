/**
 * 风险看板响应式（改进方案 5.4.5 / 5.6）失败方式：
 * F1 1280 宽度下详情仍占 452px，队列被挤到横向滚动。
 * F2 <1180 时详情掉到队列下方，点开后在首屏看不到。
 * F4 图例“高风险会话”是金点，图上是红菱形，对不上（5.4）。
 * F5 风险等级/类型/商品线索三块高度不一，风险等级下方空一大块（5.4）。
 * F3 抽屉模式下详情无最大宽度，在 390 宽手机上溢出。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(__dirname, 'concept.css'), 'utf8').replace(/\s+/g, ' ')

describe('风险看板响应式', () => {
  it('F1 1280 宽度详情收窄为 420', () => {
    expect(css).toMatch(/@media \(max-width: 1360px\) \{[^}]*\.yt-risk-md\.has-detail \{ grid-template-columns: minmax\(0, 1fr\) 420px; \}/)
  })
  it('F2/F3 <1180 详情改为右侧抽屉且不超过视口', () => {
    const block = css.match(/@media \(max-width: 1179px\) \{(.*?)\} \}/)?.[1] ?? ''
    expect(block).toMatch(/\.yt-risk-md\.has-detail \{ grid-template-columns: minmax\(0, 1fr\); \}/)
    expect(block).toMatch(/\.yt-risk-detail \{[^}]*position: fixed;[^}]*width: min\(420px, 100vw\);/)
  })
  it('F4 图例高风险会话与图上菱形同为红色', () => {
    expect(css).toMatch(/\.yt-risk-page \.yt-legend i\.is-marker \{ background: var\(--m-fury\);/)
  })
  it('F5 三块面板等高，风险等级数字放大', () => {
    expect(css).toMatch(/\.yt-risk-page \.yt-monitor-grid \{[^}]*align-items: stretch;/)
    expect(css).toMatch(/\.yt-risk-page \.yt-level-legend b \{[^}]*font-size: 2\dpx;/)
  })
})

