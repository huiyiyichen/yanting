import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright'

const output = resolve('../../output/playwright')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const report = { checks: [], screenshots: [], errors: [] }
page.on('pageerror', (e) => report.errors.push(e.message))
const api = async (path, { method = 'GET', body, role = 'support' } = {}) => {
  const response = await fetch(`http://127.0.0.1:8000${path}`, {
    method, headers: { 'Content-Type': 'application/json', 'X-Demo-View-Role': role },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const result = await response.json()
  assert.equal(response.ok, true, `${path}: ${response.status} ${JSON.stringify(result)}`)
  return result
}
const makeManual = async (name) => {
  const c = await api('/api/customer/conversations', { method: 'POST', body: { customerId: name }, role: 'customer' })
  await api(`/api/customer/conversations/${c.conversationId}/handoff`, { method: 'POST', role: 'customer' })
  return c.conversationId
}
const send = (cid, body, key) => api(`/api/customer/conversations/${cid}/messages`, {
  method: 'POST', role: 'customer', body: { body, clientMessageKey: key },
})
const find = async (cid) => (await api('/api/support/desk/risks')).find((r) => r.conversationIds.includes(cid))
const shot = async (name) => {
  await page.waitForTimeout(350)
  await page.screenshot({ path: resolve(output, `risk-v2-${name}.png`) })
  const overflow = await page.evaluate(() => Math.max(globalThis.document.body.scrollWidth, globalThis.document.documentElement.scrollWidth) - globalThis.innerWidth)
  assert.ok(overflow <= 1, `overflow: ${name}`)
  report.screenshots.push({ name, overflow })
}
const confirm = async (button, note, status = 200) => {
  await page.getByRole('button', { name: button }).click()
  await page.getByLabel('处置说明', { exact: true }).fill(note)
  const result = page.waitForResponse((r) => /\/desk\/risks\/[^/]+\/status$/.test(r.url()) && r.request().method() === 'POST')
  await page.getByRole('button', { name: /^确\s*认$/ }).click()
  const response = await result
  assert.equal(response.status(), status, await response.text())
}
try {
  const buyer = `RISK-QA-${Date.now()}`
  const cid = await makeManual(buyer)
  report.conversationId = cid
  await send(cid, '请查询订单进度', 'b')
  await send(cid, '一直没处理，再不解决我就投诉', 'r1')
  await page.goto('http://127.0.0.1:5173/risk')
  await page.getByLabel('搜索风险', { exact: true }).fill(buyer)
  await page.getByRole('button', { name: /查\s*看/ }).click()
  await confirm(/介入处理/, '第一轮介入')
  await confirm(/复核关闭/, '第一轮关闭')
  const closed = await find(cid)
  assert.equal(closed.riskStatus, 'resolved')
  const frozen = (await api(`/api/support/desk/risks/${closed.incidentId}`)).episodes
  assert.ok(frozen.length >= 1)
  await page.getByRole('tab', { name: '历史轮次' }).click()
  await shot('closed-evidence')
  await send(cid, '现在又没处理好，我要再次投诉', 'r2')
  const recurring = await find(cid)
  assert.equal(recurring.riskStatus, 'pending')
  assert.equal(recurring.recurrenceCount, 1)
  const after = await api(`/api/support/desk/risks/${recurring.incidentId}`)
  assert.deepEqual(after.episodes, frozen)
  await confirm(/重新介入/, '旧页面不能覆盖新风险', 409)
  await page.getByRole('tab', { name: '风险与证据' }).click()
  await shot('recurrence')
  report.checks.push('new complaint opens a new round; closed evidence unchanged; stale decision rejected')

  await confirm(/介入处理/, '第二轮介入')
  await confirm(/复核关闭/, '第二轮关闭')
  await confirm(/重新介入/, '人工重新核查')
  const reopened = await find(cid)
  assert.equal(reopened.riskStatus, 'in_progress')
  assert.equal(reopened.recurrenceCount, 2)
  report.checks.push('manual reopening preserves prior rounds')
  for (const [width, height] of [[1440, 900], [1280, 800], [390, 844]]) {
    await page.setViewportSize({ width, height })
    await page.getByRole('tab', { name: '历史轮次' }).click()
    await shot(`history-${width}`)
  }

  const deadlineBuyer = `DUE-QA-${Date.now()}`
  const dueCid = await makeManual(deadlineBuyer)
  let ticket = await api('/api/support/desk/tickets', { method: 'POST', body: {
    title: '到期监测验证', conversationId: dueCid, workOrderType: 'logistics',
    assignee: '当前客服', note: '验证约定时间到期提醒',
    dueAt: new Date(Date.now() + 4000).toISOString(),
  } })
  assert.equal(await find(dueCid), undefined)
  let overdue
  for (let i = 0; i < 35; i++) {
    await new Promise((done) => setTimeout(done, 1000))
    overdue = await find(dueCid)
    if (overdue) break
  }
  assert.ok(overdue, 'background monitor did not detect the elapsed deadline')
  assert.ok(overdue.signals.some((s) => s.riskType === 'work_order_overdue'))
  for (const status of ['in_progress', 'resolved']) {
    ticket = await api(`/api/support/desk/tickets/${ticket.ticketId}`, { method: 'PUT', body: {
      expectedRevision: ticket.revision, status, priority: 'normal', assignee: '当前客服',
      note: '本地跟进完成，不自动关闭风险', dueAt: ticket.dueAt,
    } })
  }
  const review = await find(dueCid)
  assert.equal(review.riskStatus, 'pending')
  assert.equal(review.signalActive, false)
  assert.equal(review.needsReview, true)
  report.checks.push('background deadline detection; ticket completion only marks risk for review')
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('http://127.0.0.1:5173/risk')
  await page.getByRole('tab', { name: '干预后复核' }).click()
  await page.getByLabel('搜索风险', { exact: true }).fill(deadlineBuyer)
  await shot('deadline-review')
  for (const id of [cid, dueCid]) {
    const audit = await api(`/api/support/audit/${id}`)
    assert.equal(audit.some((e) => e.eventType === 'model_call'), false)
  }
  assert.equal(report.errors.length, 0, report.errors.join('\n'))
} catch (error) {
  report.failure = String(error)
  await page.screenshot({ path: resolve(output, 'risk-v2-failure.png') }).catch(() => {})
  process.exitCode = 1
} finally {
  await writeFile(resolve(output, 'risk-v2-walk.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
}
