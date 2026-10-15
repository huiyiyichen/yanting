/// <reference types="node" />
/**
 * 字体子集。
 * F1 界面新增文字不在子集里，渲染时回落到系统字体，同一行字形混杂；
 * F2 @font-face 未用 swap，首屏等字体白字；
 * F3 字体栈未引用子集字体，打包了却不生效。
 */
import { describe, expect, it } from 'vitest'
import charsetText from '../../public/fonts/charset.txt?raw'
import { readFileSync } from 'node:fs'

const css = (name: string) => readFileSync(`${process.cwd()}/src/styles/${name}`, 'utf8')
const sources = import.meta.glob<string>(['../**/*.{ts,tsx,css}'], { query: '?raw', import: 'default', eager: true })

describe('字体子集', () => {
  it('源码中出现的中文字符都在子集里', () => {
    const charset = new Set(charsetText)
    const missing = new Set<string>()
    for (const text of Object.values(sources)) for (const ch of text) if (/[\u3400-\u9fff]/.test(ch) && !charset.has(ch)) missing.add(ch)
    expect([...missing].join('')).toBe('')
  })
  it('三档字重 swap 加载，并进入字体栈', () => {
    const fonts = css('fonts.css')
    expect(fonts.match(/@font-face/g)).toHaveLength(3)
    expect(fonts.match(/font-display: swap/g)).toHaveLength(3)
    expect(css('concept.css')).toMatch(/--yt-sans:[^;]*"YT Sans"/)
  })
})
