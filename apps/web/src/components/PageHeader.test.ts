/**
 * 统一页头（P2-2）。
 * H1 各业务页各写一套标题栏，样式与位置不一致，切页时页头跳动；
 * H2 新页面绕开统一页头，丢掉演示客服切换。
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const pagesDir = join(process.cwd(), 'src', 'pages')
const BUSINESS_PAGES = ['SupportWorkbench', 'RiskDashboardPage', 'WorkOrderPage', 'PlatformPages', 'ModelConfigPage', 'PromptTemplatePage']

describe('PageHeader', () => {
  it.each(BUSINESS_PAGES)('%s 使用统一页头', (name) => {
    const source = readFileSync(join(pagesDir, `${name}.tsx`), 'utf8')
    expect(source).toContain('<PageHeader')
    expect(source).not.toContain('yt-page-head')
  })
  it('页面目录没有遗漏', () => {
    const pages = readdirSync(pagesDir).filter((file) => file.endsWith('.tsx') && !file.includes('.test.') && file !== 'CustomerView.tsx')
    expect(pages.map((file) => file.replace('.tsx', '')).sort()).toEqual([...BUSINESS_PAGES].sort())
  })
})
