import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright'

// Inspect existing verified results without sending messages or making model calls.
const cid = process.argv[2]
assert.ok(cid, 'Provide a conversation with an existing grounded assistant result')
const output = resolve('../../output/playwright')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage()
const report = { conversationId: cid, screenshots: [], errors: [] }
page.on('pageerror', (error) => report.errors.push(error.message))
try {
  for (const [width, height] of [[1440, 900], [1280, 800], [390, 844]]) {
    await page.setViewportSize({ width, height })
    await page.goto(`http://127.0.0.1:5173/support?conversation=${encodeURIComponent(cid)}`)
    if (width < 1180) await page.getByRole('button', { name: '接待辅助', exact: true }).click()
    await page.getByRole('tab', { name: '服务记忆', exact: true }).click()
    await page.getByRole('heading', { name: '已知信息', exact: true }).waitFor()
    await page.locator('.evidence-quote:visible').first().waitFor()
    await page.screenshot({ path: resolve(output, `memory-${width}.png`) })
    const overflow = await page.evaluate(() => globalThis.document.documentElement.scrollWidth - globalThis.innerWidth)
    assert.ok(overflow <= 1)
    report.screenshots.push({ view: 'memory', width, overflow })
    await page.getByRole('tab', { name: 'AI 辅助', exact: true }).click()
    const trace = page.getByRole('heading', { name: '执行记录', exact: true })
    await trace.scrollIntoViewIfNeeded()
    await page.getByText('独立事实核验', { exact: false }).first().waitFor()
    await page.screenshot({ path: resolve(output, `workflow-${width}.png`) })
    report.screenshots.push({ view: 'workflow', width })
  }
  assert.deepEqual(report.errors, [])
} catch (error) {
  report.failure = String(error)
  process.exitCode = 1
} finally {
  await writeFile(resolve(output, 'grounded-memory-walk.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
}
