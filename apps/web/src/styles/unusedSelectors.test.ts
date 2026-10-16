/**
 * CSS 去重（P2-2）。
 * S1 删掉组件后样式残留，三份样式表越叠越厚，后加载的覆盖难以追查；
 * S2 旧类名（旧侧栏、旧话术候选、旧档案卡）复活时被残留规则意外命中。
 * 守则：样式表里的类名必须在源码中出现；is-* 状态修饰与 antd 内部类除外（常由模板字符串拼出）。
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = join(process.cwd(), 'src')
const walk = (dir: string): string[] => readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
  entry.isDirectory() ? walk(join(dir, entry.name)) : [join(dir, entry.name)])
const source = walk(root).filter((file) => /\.tsx?$/.test(file) && !file.includes('.test.')).map((file) => readFileSync(file, 'utf8')).join('\n')

const selectorClasses = (css: string) => new Set([...css.replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/\{[^{}]*\}/g, '{}').matchAll(/\.([a-zA-Z_][\w-]*)/g)].map((match) => match[1]))

describe('样式表无残留类名', () => {
  it.each(['global.css', 'concept.css', 'yanting.css'])('%s', (name) => {
    const css = readFileSync(join(root, 'styles', name), 'utf8')
    const unused = [...selectorClasses(css)].filter((cls) =>
      !cls.startsWith('is-') && !cls.startsWith('ant') && !source.includes(cls))
    expect(unused).toEqual([])
  })
})
