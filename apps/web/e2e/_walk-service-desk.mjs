import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { chromium } from 'playwright'

const output = resolve('../../output/playwright')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const failures = []
const report = { screenshots: [], workflows: [], failures }
const base = process.env.ANKER_AGENT_WEB_BASE ?? 'http://127.0.0.1:5173'
page.on('pageerror', (error) => failures.push(error.message))
page.on('response', (response) => {
  if (response.status() >= 500) failures.push(`${response.status()} ${response.url()}`)
})
const api = async (path, body, role = 'support') => {
  const response = await fetch(`http://127.0.0.1:8000${path}`, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', 'X-Demo-View-Role': role },
    body: body ? JSON.stringify(body) : undefined,
  })
  assert.equal(response.ok, true, `${path}: ${response.status}`)
  return response.json()
}
const updateTicketApi = async (ticket) => {
  const response = await fetch(`http://127.0.0.1:8000/api/support/desk/tickets/${ticket.ticketId}`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      'X-Demo-View-Role': 'support',
      'X-Demo-Operator': 'G001',
    },
    body: JSON.stringify({
      expectedRevision: ticket.revision,
      status: 'in_progress',
      priority: ticket.priority,
      assignee: ticket.assignee || 'G001',
      dueAt: ticket.dueAt,
      note: '已受理，等待仓库反馈。',
      localDetail: ticket.localDetail,
    }),
  })
  assert.equal(response.ok, true, `${ticket.ticketId}: ${response.status}`)
  return response.json()
}
const shot = async (name) => {
  await page.screenshot({ path: resolve(output, `desk-${name}.png`), fullPage: false })
  const overflow = await page.evaluate(() => Math.max(globalThis.document.body.scrollWidth, globalThis.document.documentElement.scrollWidth) - globalThis.innerWidth)
  assert.ok(overflow <= 1, `${name}: root overflow ${overflow}`)
  report.screenshots.push({ name, overflow })
}
const followTicket = async (ticket) => {
  await page.goto(base + `/platform/work-orders?ticket=${ticket.ticketId}`)
  if (ticket.status !== 'in_progress') {
    await page.getByLabel('处理状态', { exact: true }).click()
    const processingOption = page.getByRole('option', { name: '处理中', exact: true })
    await processingOption.waitFor({ state: 'visible', timeoutMs: 10000 })
    await processingOption.click()
  }
  await page.getByLabel('跟进记录', { exact: true }).fill('已受理，等待仓库反馈。')
  const updated = page.waitForResponse((r) => {
    const url = new URL(r.url())
    return url.pathname.endsWith(`/api/support/desk/tickets/${ticket.ticketId}`)
      && r.request().method() === 'PUT'
  })
  await page.getByRole('button', { name: /保存跟进/ }).click()
  assert.equal((await (await updated).json()).status, 'in_progress')
  await page.reload()
  const matchingNotes = page.getByRole('listitem').filter({ hasText: '已受理，等待仓库反馈。' })
  await matchingNotes.first().waitFor()
  await shot('ticket-followup')
  report.workflows.push('ticket handling and persisted history')
}
try {
  if (process.argv.includes('--ticket-only')) {
    const tickets = await api('/api/support/desk/tickets')
    const ticket = tickets.find((t) => t.title === '联动验证：物流跟进'
      && ['pending', 'in_progress'].includes(t.status))
    assert.ok(ticket)
    await followTicket(ticket)
  } else {
  const routes = [
    ['support', '/support?conversation=S00001', '客服工作台'],
    ['risk', '/risk', '风险预警'],
    ['tickets', '/platform/work-orders', '工单管理'],
    ['knowledge', '/platform/knowledge', '知识库'],
    ['prompts', '/platform/prompts', 'Prompt 管理'],
  ]
  for (const [width, height] of (process.argv.includes('--flows-only') ? [] : [[1440, 900], [1280, 800], [390, 844]])) {
    await page.setViewportSize({ width, height })
    for (const [name, path, title] of routes) {
      await page.goto(base + path)
      await page.getByRole('heading', { name: title, exact: true }).waitFor()
      await page.waitForTimeout(1200)
      assert.equal(await page.getByRole('navigation', { name: '主导航' }).getByRole('link').count(), 7)
      await shot(`${name}-${width}`)
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(base + '/risk')
  await page.getByRole('button', { name: /查\s*看/ }).first().click()
  await page.getByRole('tab', { name: '风险与证据' }).waitFor()
  await shot('risk-detail')
  await page.getByRole('tab', { name: '关联工单' }).click()
  await shot('risk-linked-tickets')
  report.workflows.push('risk evidence and linked tickets')

  await page.goto(base + '/platform/knowledge')
  await page.getByRole('button', { name: /编辑.*片段/ }).first().click()
  await page.getByLabel('正文', { exact: true }).waitFor()
  assert.ok((await page.getByLabel('正文', { exact: true }).inputValue()).length > 0)
  await page.getByRole('tab', { name: /已保存片段/ }).click()
  await shot('knowledge-chunks')
  report.workflows.push('knowledge source and chunk preview')

  await page.goto(base + '/platform/prompts')
  await page.getByRole('button', { name: /版\s*本/ }).first().click()
  await page.getByText('版本记录', { exact: true }).waitFor()
  await shot('prompt-revisions')
  report.workflows.push('prompt version readback')

  const customer = await context.newPage()
  await customer.goto(base + '/customer')
  const createdResponse = customer.waitForResponse((r) => r.url().endsWith('/api/customer/conversations') && r.request().method() === 'POST')
  await customer.getByRole('button', { name: '新建会话', exact: true }).click()
  const created = await (await createdResponse).json()
  const cid = created.conversationId
  await api(`/api/customer/conversations/${cid}/handoff`, {}, 'customer')
  const source = await api('/api/support/conversations/S00001/service-context')
  const order = source.orders[0].orderId
  const text = `联动检查：订单 ${order}，请核对物流。`
  await customer.getByLabel('客户消息输入框').fill(text)
  const sendResponse = customer.waitForResponse((r) => r.url().endsWith(`/conversations/${cid}/messages`) && r.request().method() === 'POST')
  await customer.getByRole('button', { name: '发送', exact: true }).click()
  await sendResponse
  await page.goto(base + `/support?conversation=${cid}`)
  await page.getByText(text, { exact: true }).last().waitFor()
  await page.getByRole('tab', { name: /订单 [1-9]/ }).click()
  await page.getByText(order, { exact: true }).waitFor()
  const reply = '已看到订单和历史记录，我先核对当前物流进展。'
  await page.getByLabel('客服回复输入框').fill(reply)
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await customer.getByRole('log', { name: '消息列表' }).getByText(reply, { exact: true }).waitFor()
  report.workflows.push('customer/support bidirectional messages and exact order linkage')
  await shot('linked-reception')

  await page.getByRole('button', { name: /建工单/ }).click()
  await page.getByLabel('事项', { exact: true }).fill('联动验证：物流跟进')
  await page.getByLabel('物流问题描述', { exact: true }).fill('核对订单物流进展。')
  await page.getByLabel('事项说明', { exact: true }).fill('核对订单物流，并记录本地处理进度。')
  const ticketResponse = page.waitForResponse((r) => {
    const url = new URL(r.url())
    return url.pathname === '/api/support/desk/tickets' && r.request().method() === 'POST'
  })
  await page.getByRole('button', { name: /创\s*建/ }).click()
  const ticket = await (await ticketResponse).json()
  assert.ok(ticket.ticketId, JSON.stringify(ticket))
  report.workflows.push('ticket creation')
  if (ticket.status === 'pending') {
    await updateTicketApi(ticket)
    await page.reload()
    await page.getByText('已受理，等待仓库反馈。', { exact: true }).first().waitFor()
    await shot('ticket-followup')
    report.workflows.push('ticket handling and persisted history')
  } else {
    await followTicket(ticket)
  }
  }
  assert.equal(failures.length, 0, failures.join('\n'))
} catch (error) {
  report.error = String(error)
  await page.screenshot({ path: resolve(output, 'desk-walk-failure.png') }).catch(() => {})
  process.exitCode = 1
} finally {
  await writeFile(resolve(output, process.argv.includes('--ticket-only') ? 'desk-ticket.json' : process.argv.includes('--flows-only') ? 'desk-flows.json' : 'desk-walk.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report, null, 2))
  await browser.close()
}
