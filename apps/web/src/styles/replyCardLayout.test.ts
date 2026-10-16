/**
 * 回复卡布局（全景方案 5.3 / 反馈 ②）失败方式：
 * F1 回复卡用负外边距撑出面板，压住下方“风险关注”并出现横向滚动条。
 * F2 引用事实的片段整段金棕色，正文不可区分。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = ['yanting.css', 'concept.css'].map((name) => readFileSync(resolve(__dirname, name), 'utf8')).join('\n').replace(/\s+/g, ' ')
const rules = (selector: string) => [...css.matchAll(new RegExp(`(?:^|\\})\\s*${selector.replace(/[.]/g, '\\.')} \\{([^}]*)\\}`, 'g'))].map((m) => m[1])

describe('回复卡布局', () => {
  it('F1 回复卡不使用负外边距或固定宽度', () => {
    const body = rules('.reception-plugin .yt-reply').join(';')
    expect(body).not.toMatch(/margin:[^;]*-\d/)
    expect(body).not.toMatch(/(?:^|;)\s*width:\s*\d/)
  })
  it('F2 事实引用沿用正文色，仅金色下划线', () => {
    const ref = rules('.reception-plugin .yt-reply-ref').join(';')
    expect(ref).toMatch(/color: inherit/)
    expect(ref).toMatch(/border-bottom: 1px dashed/)
  })
})
