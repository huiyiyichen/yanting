import { mkdirSync } from 'node:fs'
import { chromium } from 'playwright-core'

/**
 * 视觉走查截图（手工工具，不是测试用例）。
 *
 * 打开发的前后端，造一条有真实模型回复的会话，把客服/客户两个视角在
 * 1440×900 与 390×844 下截图到 `%TEMP%\anker-shots\`，用于和参考图逐块比对。
 *
 * 运行（前后端已在 8000/5173 跑起来后）：
 *     cd code\apps\web
 *     node e2e\_shot.mjs
 */
const OUT = process.env.ANKER_SHOT_DIR ?? `${process.env.TEMP}\\anker-shots`
mkdirSync(OUT, { recursive: true })

const CUSTOMER = { 'X-Demo-View-Role': 'customer' }
const BASE = 'http://127.0.0.1:5173'
const marker = String(Date.now()).slice(-5)

const browser = await chromium.launch({ channel: 'chrome' })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const errors = []
const warnings = []
page.on('pageerror', (e) => errors.push(String(e).slice(0, 200)))
page.on('console', (m) => {
  const text = m.text()
  if (m.type() === 'error' && !text.includes('favicon')) errors.push(text.slice(0, 200))
  // antd 的废弃 API 提示走的是 warning，必须单独收集：
  // 只看 error 会漏掉「用了旧 API 但暂时还能跑」的情况（已踩过）。
  if (m.type() === 'warning' && /\[antd|\[antdx/.test(text)) warnings.push(text.slice(0, 200))
})

try {
  // 造数据：一个新会话 + 一条会触发检索与消歧的客户消息
  const created = await page.request.post(`${BASE}/api/customer/conversations`, {
    headers: CUSTOMER,
    data: {},
  })
  const conversationId = (await created.json()).conversationId
  await page.request.post(`${BASE}/api/customer/conversations/${conversationId}/messages`, {
    headers: CUSTOMER,
    data: {
      body: `[${marker}] A1 Pro 无线吸尘器吸力变弱，中国大陆官网购买，怎么排查？`,
      clientMessageKey: `shot-${marker}`,
    },
  })
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(500)
    const res = await page.request.get(
      `${BASE}/api/customer/conversations/${conversationId}/messages`,
      { headers: CUSTOMER },
    )
    const list = await res.json()
    if (list.some((m) => m.senderRole === 'assistant')) break
  }
  console.log('conversation:', conversationId, 'marker:', marker)

  const views = [
    { name: 'support', path: '/support', width: 1440, height: 900 },
    { name: 'support-narrow', path: '/support', width: 390, height: 844 },
    { name: 'customer', path: '/customer', width: 1440, height: 900 },
    { name: 'customer-narrow', path: '/customer', width: 390, height: 844 },
    // 平台管理页：改完都过一遍，确认渲染无异常（不需要选中会话）
    { name: 'platform-models', path: '/platform/models', width: 1440, height: 900 },
    { name: 'platform-knowledge', path: '/platform/knowledge', width: 1440, height: 900 },
    { name: 'platform-prompts', path: '/platform/prompts', width: 1440, height: 900 },
    { name: 'platform-work-orders', path: '/platform/work-orders', width: 1440, height: 900 },
    { name: 'platform-jev', path: '/platform/jev', width: 1440, height: 900 },
  ]

  for (const view of views) {
    await page.setViewportSize({ width: view.width, height: view.height })
    await page.goto(`${BASE}${view.path}`)
    await page.waitForTimeout(1500)

    // 客服视角额外生成一次话术候选，用来核对该面板的视觉（真实模型调用，约 2 秒）
    if (view.name.startsWith('support')) {
      const generated = await page.request.post(
        `${BASE}/api/support/conversations/${conversationId}/suggestions/generate`,
        { headers: { 'X-Demo-View-Role': 'support' } },
      )
      console.log('suggestions:', generated.status())
    }

    // 选中本次造的会话（窄屏先展开列表）
    const listName = view.name.startsWith('support') ? '会话队列' : '我的售后会话'
    const expandName = view.name.startsWith('support') ? '展开会话队列' : /会话列表/
    const list = page.getByRole('complementary', { name: listName })
    if (!(await list.isVisible().catch(() => false))) {
      const expand = page.getByRole('button', { name: expandName })
      if (await expand.count()) {
        await expand.first().click().catch(() => undefined)
        await page.waitForTimeout(800)
      }
    }
    const target = page.getByRole('complementary', { name: listName }).getByRole('button').filter({ hasText: marker }).first()
    if (await target.count()) {
      await target.click().catch(() => undefined)
      await page.waitForTimeout(1800)
    }
    const path = `${OUT}\\${view.name}.png`
    await page.screenshot({ path, fullPage: false })
    console.log('shot:', path)
  }
  console.log('page errors:', JSON.stringify(errors.slice(0, 5)))
  console.log('antd 警告:', JSON.stringify(warnings.slice(0, 5)))

  // ── 分能力配置抽屉（用户反馈③）：模型配置页每行「配置」打开的二级配置 ──
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`${BASE}/platform/models`)
  await page.waitForTimeout(1500)
  // 注意：左栏导航项「模型配置」也是 button，按名字模糊匹配会先命中它
  // （实测点到了导航、抽屉没打开），因此必须限定在表格内。
  const configButtonAt = (rowIndex) =>
    page.locator('.ant-table tbody tr').nth(rowIndex).getByRole('button', { name: '配置' })

  for (const [rowIndex, name, title] of [
    [0, 'platform-models-drawer', '文本模型（LLM）'],
    [3, 'platform-rerank-drawer', '重排序模型'],
    [2, 'platform-embedding-drawer', '向量模型（编码）'],
  ]) {
    const button = configButtonAt(rowIndex)
    if ((await button.count()) === 0) {
      console.log(`第 ${rowIndex} 行没有「配置」按钮：${name} 未截图`)
      continue
    }
    await button.click()
    await page
      .locator('.ant-drawer-title')
      .first()
      .waitFor({ state: 'visible', timeout: 5_000 })
      .catch(() => undefined)
    await page.waitForTimeout(800)
    const drawerTitle =
      (await page
        .locator('.ant-drawer-title')
        .first()
        .textContent()
        .catch(() => null)) ?? '（没有标题）'
    const controls = await page.locator('.ant-drawer input').count()
    // 把「抽屉真的开了、里面有可填控件」写成可核对的一行输出，
    // 避免只看截图就下结论（第 51 项那类「证据与描述不符」的教训）
    console.log(`抽屉[${title}] 实际标题:`, drawerTitle, '| 输入控件数:', controls)
    await page.screenshot({ path: `${OUT}\\${name}.png` })
    console.log('shot:', `${OUT}\\${name}.png`)
    await page.keyboard.press('Escape')
    await page.waitForTimeout(600)
  }

  // ── 新会话开场白与快捷入口（用户反馈⑤之二） ──
  const freshMarker = `${marker}F`
  const fresh = await page.request.post(`${BASE}/api/customer/conversations`, {
    headers: CUSTOMER,
    data: { title: `[${freshMarker}] 开场白走查` },
  })
  const freshId = (await fresh.json()).conversationId
  await page.goto(`${BASE}/customer`)
  await page.waitForTimeout(1500)
  const freshList = page.getByRole('complementary', { name: '我的售后会话' })
  if (!(await freshList.isVisible().catch(() => false))) {
    await page
      .getByRole('button', { name: /会话列表/ })
      .first()
      .click()
      .catch(() => undefined)
    await page.waitForTimeout(800)
  }
  const freshRow = page
    .getByRole('complementary', { name: '我的售后会话' })
    .getByRole('button')
    .filter({ hasText: freshMarker })
    .first()
  if (await freshRow.count()) {
    await freshRow.click().catch(() => undefined)
  }
  await page.waitForTimeout(1200)
  const quickVisible = await page
    .getByRole('button', { name: '吸力变弱怎么排查' })
    .isVisible()
    .catch(() => false)
  console.log('快捷入口可见:', quickVisible, '| 会话:', freshId)
  await page.screenshot({ path: `${OUT}\\customer-onboarding.png` })
  console.log('shot:', `${OUT}\\customer-onboarding.png`)

  // ── 结束服务后的客户评价入口（用户反馈⑤） ──
  const closeMarker = `${marker}C`
  const created2 = await page.request.post(`${BASE}/api/customer/conversations`, {
    headers: CUSTOMER,
    data: {},
  })
  const closeConversationId = (await created2.json()).conversationId
  await page.request.post(`${BASE}/api/customer/conversations/${closeConversationId}/messages`, {
    headers: CUSTOMER,
    data: {
      body: `[${closeMarker}] 结束服务走查：吸力变弱，帮我看看`,
      clientMessageKey: `shot-close-${closeMarker}`,
    },
  })
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(500)
    const res = await page.request.get(
      `${BASE}/api/customer/conversations/${closeConversationId}/messages`,
      { headers: CUSTOMER },
    )
    const list = await res.json()
    if (list.some((m) => m.senderRole === 'assistant')) break
  }
  const closed = await page.request.post(
    `${BASE}/api/support/conversations/${closeConversationId}/close`,
    { headers: { 'X-Demo-View-Role': 'support' }, data: { reason: '走查：结束服务' } },
  )
  console.log('close:', closed.status(), JSON.stringify(await closed.json()))

  await page.goto(`${BASE}/customer`)
  await page.waitForTimeout(1500)
  const closeList = page.getByRole('complementary', { name: '我的售后会话' })
  if (!(await closeList.isVisible().catch(() => false))) {
    await page
      .getByRole('button', { name: /会话列表/ })
      .first()
      .click()
      .catch(() => undefined)
    await page.waitForTimeout(800)
  }
  const closeTarget = page
    .getByRole('complementary', { name: '我的售后会话' })
    .getByRole('button')
    .filter({ hasText: closeMarker })
    .first()
  if (await closeTarget.count()) {
    await closeTarget.click().catch(() => undefined)
  }
  await page.waitForTimeout(1800)
  await page.screenshot({ path: `${OUT}\\customer-rating.png` })
  console.log('shot:', `${OUT}\\customer-rating.png`)
  console.log('page errors（含两条新视图）:', JSON.stringify(errors.slice(0, 8)))
  console.log('antd 警告（含两条新视图）:', JSON.stringify(warnings.slice(0, 8)))
} finally {
  await browser.close()
}
