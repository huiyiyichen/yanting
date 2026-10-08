import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright'

// One reception turn includes drafting, verification and at most one repair.
const output = resolve('../../output/playwright')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const customer = await context.newPage()
const support = await context.newPage()
const report = { checks: [], screenshots: [], errors: [] }
for (const page of [customer, support]) page.on('pageerror', (error) => report.errors.push(error.message))
const base = 'http://127.0.0.1:5173'
const api = async (path, role = 'support') => {
  const response = await fetch(`http://127.0.0.1:8000${path}`, { headers: { 'X-Demo-View-Role': role } })
  assert.equal(response.ok, true, `${path}: ${response.status}`)
  return response.json()
}
const shot = async (page, name) => {
  await page.screenshot({ path: resolve(output, `auto-${name}.png`) })
  const overflow = await page.evaluate(() => Math.max(globalThis.document.body.scrollWidth, globalThis.document.documentElement.scrollWidth) - globalThis.innerWidth)
  assert.ok(overflow <= 1, `${name}: overflow ${overflow}`)
  report.screenshots.push({ name, overflow })
}
try {
  const source = await api('/api/support/conversations/S00001/service-context')
  await customer.goto(base + '/customer')
  const creation = customer.waitForResponse((r) => r.url().endsWith('/api/customer/conversations') && r.request().method() === 'POST')
  await customer.getByRole('button', { name: '新建会话', exact: true }).click()
  const created = await (await creation).json()
  const cid = created.conversationId
  report.conversationId = cid
  assert.equal(created.serviceMode, 'autonomous')
  const text = `订单 ${source.orders[0].orderId} 现在是什么物流状态？我有点着急，请帮我看一下已有记录。`
  await customer.getByLabel('客户消息输入框').fill(text)
  const send = customer.waitForResponse((r) => r.url().endsWith(`/conversations/${cid}/messages`) && r.request().method() === 'POST')
  const started = Date.now()
  await customer.getByRole('button', { name: '发送', exact: true }).click()
  assert.equal((await send).ok(), true)
  report.ackMilliseconds = Date.now() - started
  let automatic
  for (let i = 0; i < 120; i++) {
    const rows = await api(`/api/customer/conversations/${cid}/messages`, 'customer')
    const lastCustomer = rows.findIndex((r) => r.body === text)
    automatic = rows.slice(lastCustomer + 1).find((r) => r.senderRole === 'assistant')
    if (automatic) break
    const list = await api('/api/customer/conversations', 'customer')
    const item = list.find((r) => r.conversationId === cid)
    if (item?.serviceMode === 'operator_assisted') throw new Error(`Unexpected handoff: ${item.autoReplyStatus}`)
    await new Promise((done) => setTimeout(done, 1000))
  }
  assert.ok(automatic, 'No automatic reply within 120 seconds')
  report.replySeconds = (Date.now() - started) / 1000
  report.reply = automatic.body
  const assistant = await api(`/api/support/conversations/${cid}/assistant`)
  assert.equal(assistant.isMock, false)
  assert.equal(assistant.deliveryMode, 'automatic')
  assert.equal(assistant.verificationStatus, 'verified')
  assert.ok(assistant.modelUsage.calls >= 2 && assistant.modelUsage.calls <= 4)
  assert.ok(assistant.replySuggestions.some((r) => r.claims.length > 0))
  const memory = await api(`/api/support/reception/${cid}/memory`)
  assert.equal(memory.verified, true)
  assert.equal(memory.stale, false)
  assert.ok(memory.items.length > 0)
  assert.ok(memory.items.every((item) => memory.sources.some((s) => s.sourceId === item.sourceRef && s.text.includes(item.quote))))
  report.memoryItems = memory.items.length
  report.usage = assistant.modelUsage
  report.workflow = assistant.workflowSteps
  report.model = assistant.modelId
  report.checks.push('real model automatically replied without operator confirmation')
  await customer.getByRole('log', { name: '消息列表' }).getByText(automatic.body, { exact: true }).waitFor()
  await shot(customer, 'customer-replied')

  await customer.getByRole('button', { name: '转人工', exact: true }).click()
  await customer.getByText('人工接待', { exact: true }).waitFor()
  await support.goto(base + `/support?conversation=${cid}`)
  await support.getByRole('button', { name: '恢复 AI 接待', exact: true }).waitFor()
  await support.getByRole('tab', { name: '服务记忆', exact: true }).click()
  await support.getByText(memory.items[0].quote, { exact: true }).first().waitFor()
  await shot(support, 'grounded-memory')
  report.checks.push('source-backed memory persisted; reply claims verified; workflow usage recorded')
  await support.getByLabel('客服回复输入框').fill('我已接管，会继续核对这笔订单。')
  await support.getByRole('button', { name: '发送', exact: true }).click()
  await customer.getByRole('log', { name: '消息列表' }).getByText('我已接管，会继续核对这笔订单。', { exact: true }).waitFor()
  const before = (await api(`/api/customer/conversations/${cid}/messages`, 'customer')).filter((r) => r.senderRole === 'assistant').length
  await customer.getByLabel('客户消息输入框').fill('请继续帮我跟进。')
  const humanSend = customer.waitForResponse((r) => r.url().endsWith(`/conversations/${cid}/messages`) && r.request().method() === 'POST')
  await customer.getByRole('button', { name: '发送', exact: true }).click()
  await humanSend
  await new Promise((done) => setTimeout(done, 2000))
  assert.equal((await api(`/api/customer/conversations/${cid}/messages`, 'customer')).filter((r) => r.senderRole === 'assistant').length, before)
  report.checks.push('customer handoff stops automatic replies; human replies reach customer')
  await shot(support, 'human-takeover')

  await support.getByRole('button', { name: '恢复 AI 接待', exact: true }).click()
  await support.getByRole('button', { name: /^恢\s*复$/ }).click()
  await support.getByRole('button', { name: '接管会话', exact: true }).waitFor()
  assert.equal(await support.getByRole('button', { name: '发送', exact: true }).isEnabled(), false)
  report.checks.push('operator explicitly restores AI mode without replaying old messages')
  for (const [width, height] of [[1440, 900], [1280, 800], [390, 844]]) {
    await customer.setViewportSize({ width, height })
    await support.setViewportSize({ width, height })
    await shot(customer, `customer-${width}`)
    await shot(support, `support-${width}`)
  }
  assert.equal(report.errors.length, 0, report.errors.join('\n'))
} catch (error) {
  report.failure = String(error)
  await shot(customer, 'failure').catch(() => {})
  process.exitCode = 1
} finally {
  await writeFile(resolve(output, 'auto-reception-live.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
}
