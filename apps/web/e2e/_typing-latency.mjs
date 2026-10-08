import { chromium } from 'playwright-core'

/**
 * 输入延迟测量（手工工具，不是测试用例）。
 *
 * 用户反馈「在对话框输入文字时卡顿 1—2 秒」。这里量的是**按键到字符出现在输入框**
 * 的真实耗时：逐字符 `pressSequentially`，每次按键后立刻读回输入框的值，
 * 记录每次「按下 → 值变长」的耗时。逐次测量比总耗时更能说明问题（首字符含聚焦开销）。
 *
 * 运行（前后端已在 8000/5173 跑起来后）：
 *     cd code\apps\web
 *     node e2e\_typing-latency.mjs [customer|support]
 */
const BASE = 'http://127.0.0.1:5173'
const view = process.argv[2] === 'support' ? 'support' : 'customer'
const LABEL = view === 'support' ? '客服回复输入框' : '客户消息输入框'
const TEXT = '吸力变弱想问问怎么处理'

const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })

try {
  // 客服侧需要先接管才能输入；这里只量输入延迟，所以先选一个会话
  await page.goto(`${BASE}/${view}`)
  await page.waitForTimeout(2_500)

  const list = page.getByRole('complementary', {
    name: view === 'support' ? '会话队列' : '我的售后会话',
  })
  const expand = page.getByRole('button', {
    name: view === 'support' ? '展开会话队列' : /会话列表/,
  })
  if (!(await list.isVisible().catch(() => false))) {
    await expand.first().click().catch(() => undefined)
    await page.waitForTimeout(800)
  }
  const rows = list.getByRole('button')
  const rowCount = await rows.count()
  await rows.first().click().catch(() => undefined)
  await page.waitForTimeout(1_500)

  const input = page.getByLabel(LABEL)
  await input.click()
  await page.waitForTimeout(300)

  const perKey = []
  for (const char of TEXT) {
    const started = Date.now()
    await page.keyboard.type(char)
    // 等到值真的变了（React 受控组件回写完成后才算这一次按键结束）。
    // 这里用字符串表达式而不是函数：表达式在浏览器里求值，脚本本身不需要
    // 声明 `document` 这类浏览器全局量（否则 eslint 的 no-undef 会报错）。
    const expectedLength = perKey.length + 1
    await page
      .waitForFunction(
        `document.querySelector('[aria-label="${LABEL}"]')?.value.length >= ${expectedLength}`,
        undefined,
        { timeout: 30_000 },
      )
      .catch(() => undefined)
    perKey.push(Date.now() - started)
    void char
  }

  const sorted = [...perKey].sort((a, b) => a - b)
  const total = perKey.reduce((sum, item) => sum + item, 0)
  console.log(`视图=${view} | 会话条数=${rowCount} | 字符数=${perKey.length}`)
  console.log('每次按键耗时(ms):', JSON.stringify(perKey))
  console.log(
    `合计=${total}ms | 平均=${Math.round(total / perKey.length)}ms | 中位=${sorted[Math.floor(sorted.length / 2)]}ms | 最大=${sorted[sorted.length - 1]}ms`,
  )
} finally {
  await browser.close()
}
