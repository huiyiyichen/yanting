import { chromium } from 'playwright-core'

/**
 * 客户侧完整 live 走查（手工工具，**不是**测试用例）。
 *
 * 为什么不是 spec：它依赖真实的开发后端与真实模型回复，只做「人眼可读」的输出，
 * 不做断言，因而不进 `playwright test`（文件名不以 .spec 结尾，testDir 也不会收集它）。
 * 用途：改完客户侧交互后跑一遍，确认新建会话 → 发消息 → 上传图片 → 切换会话不串线
 * → 刷新恢复这条链路在真实模型下仍然通。
 *
 * 运行（前后端已在 8000/5173 跑起来后）：
 *     cd code\apps\web
 *     node e2e\_walk-customer.mjs
 */
const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
page.on('pageerror', (e) => errors.push(`pageerror: ${String(e).slice(0, 180)}`))
page.on('console', (m) => {
  const t = m.text()
  if (m.type() === 'error' && !t.includes('favicon') && !t.includes('404')) errors.push(t.slice(0, 160))
})
const log = (k, v) => console.log(`${k}: ${v}`)

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEX///+/v7+jQ3Y5AAAADklEQVQI12P4AIX8EAgALgAD/aNpbtEAAAAASUVORK5CYII=',
  'base64',
)

try {
  await page.goto('http://127.0.0.1:5173/customer')
  await page.getByRole('complementary', { name: '我的售后会话' }).waitFor({ timeout: 30_000 })
  await page.waitForTimeout(1200)

  // 1) 新建会话
  await page.getByRole('button', { name: /新建会话/ }).first().click()
  await page.waitForTimeout(2000)
  log('新建后输入框可见', await page.getByLabel('客户消息输入框').isVisible())

  // 2) 发一条会触发知识检索的消息
  const input = page.getByLabel('客户消息输入框')
  await input.fill('A1 Pro 无线吸尘器滤芯多久换一次？')
  await page.getByRole('region', { name: '客户会话内容' }).getByRole('button', { name: /发\s*送/ }).click()
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(500)
    if ((await input.inputValue()) === '') break
  }
  await page.waitForTimeout(6000)
  const logText = await page.getByRole('log', { name: '消息列表' }).textContent()
  log('客户视角回复', (logText || '').replace(/\s+/g, ' ').slice(-140))

  // 3) 上传图片（Attachments 触发 filechooser）
  const uploadBtn = page.getByRole('button', { name: '上传故障图片' })
  log('上传按钮存在', (await uploadBtn.count()) > 0)
  if ((await uploadBtn.count()) > 0) {
    const chooserPromise = page.waitForEvent('filechooser', { timeout: 10_000 }).catch(() => null)
    await uploadBtn.click()
    const chooser = await chooserPromise
    if (chooser) {
      await chooser.setFiles({ name: 'draft.png', mimeType: 'image/png', buffer: PNG })
      await page.waitForTimeout(4000)
      const attachText = (await page.locator('.ant-attachments').first().textContent().catch(() => '')) || ''
      log('附件区文本', attachText.replace(/\s+/g, ' ').slice(0, 100))
    } else {
      log('附件选择器', '未弹出 filechooser')
    }
  }

  // 4) 再发一条，然后刷新，确认以服务端恢复
  await input.fill('补充：吸力也变弱了')
  await page.getByRole('region', { name: '客户会话内容' }).getByRole('button', { name: /发\s*送/ }).click()
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(500)
    if ((await input.inputValue()) === '') break
  }
  await page.waitForTimeout(6000)
  const beforeReload = await page.getByRole('log', { name: '消息列表' }).locator('> div').count()
  await page.reload()
  await page.waitForTimeout(3000)
  await page.getByRole('complementary', { name: '我的售后会话' }).waitFor({ timeout: 30_000 })
  const list = page.getByRole('complementary', { name: '我的售后会话' })
  await list.getByRole('button').filter({ hasText: 'A1 Pro 无线吸尘器滤芯' }).first().click()
  await page.waitForTimeout(2500)
  const afterReload = await page.getByRole('log', { name: '消息列表' }).locator('> div').count()
  log('刷新前/后消息条数', `${beforeReload} / ${afterReload}`)

  // 5) 切到**另一个**会话再切回，确认不串线。
  //    注意不能用 `.first()`：会话按最新在前排序，first 可能还是本会话，
  //    那样测出来的是假结果（我第一次就踩了）。
  const headers = { 'X-Demo-View-Role': 'customer' }
  const listResp = await page.request.get(
    'http://127.0.0.1:5173/api/customer/conversations?customerId=CUST-DEMO-01',
    { headers },
  )
  const conversations = await listResp.json()
  const target = conversations.find((c) => c.title.includes('A1 Pro 无线吸尘器滤芯'))
  const other = conversations.find((c) => c.conversationId !== target?.conversationId)
  log('目标会话 id', target?.conversationId)
  log('另一会话 id', other?.conversationId)

  if (target && other) {
    await page.goto('http://127.0.0.1:5173/customer')
    await page.getByRole('complementary', { name: '我的售后会话' }).waitFor({ timeout: 30_000 })
    await page.waitForTimeout(1500)
    const freshList = page.getByRole('complementary', { name: '我的售后会话' })
    await freshList.getByRole('button').filter({ hasText: other.title }).first().click()
    await page.waitForTimeout(2500)
    const otherText = (await page.getByRole('log', { name: '消息列表' }).textContent()) || ''
    log('另一会话含本会话内容（应为 false）', otherText.includes('吸力也变弱了'))
    log('另一会话标题匹配', otherText.length > 0)
  }

  log('页面错误', JSON.stringify(errors.slice(0, 5)))
} finally {
  await browser.close()
}
