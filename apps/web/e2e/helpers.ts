import { expect, type Locator, type Page } from '@playwright/test'

/**
 * 端到端测试辅助：直接调用后端准备数据。
 *
 * 这些测试跑在**真实前后端**上（Vite 代理 /api），数据会真实落库。
 */
export const CUSTOMER = { 'X-Demo-View-Role': 'customer' }
export const SUPPORT = { 'X-Demo-View-Role': 'support' }

export interface MessageDto {
  messageId: string
  conversationId: string
  senderRole: string
  body: string
  messageRevision: number
  clientMessageKey?: string
  attachments?: { attachmentId?: string; url?: string; mimeType?: string }[]
}

/**
 * 建会话。
 *
 * `title` 可选：新会话在客户说话前标题都是「新会话」，多个用例并行/连续跑时
 * 靠"列表第一条"定位会互相串（实测：两次运行时间戳相同，排序退化成插入顺序）。
 * 需要精确定位时就显式给一个带运行标记的标题。
 */
export async function createConversation(
  page: Page,
  customerId = 'CUST-DEMO-01',
  title?: string,
): Promise<string> {
  const response = await page.request.post('/api/customer/conversations', {
    headers: CUSTOMER,
    data: title ? { customerId, title } : { customerId },
  })
  expect(response.ok()).toBeTruthy()
  return (await response.json()).conversationId as string
}

export async function listMessages(
  page: Page,
  conversationId: string,
  role: 'customer' | 'support' = 'customer',
): Promise<MessageDto[]> {
  const response = await page.request.get(
    `/api/${role}/conversations/${conversationId}/messages`,
    { headers: role === 'customer' ? CUSTOMER : SUPPORT },
  )
  expect(response.ok()).toBeTruthy()
  return (await response.json()) as MessageDto[]
}

export async function sendCustomerMessage(
  page: Page,
  conversationId: string,
  body: string,
  clientMessageKey: string,
): Promise<{ message: MessageDto; created: boolean }> {
  const response = await page.request.post(
    `/api/customer/conversations/${conversationId}/messages`,
    { headers: CUSTOMER, data: { body, clientMessageKey } },
  )
  const text = await response.text()
  if (!response.ok()) {
    // 把真实状态码与响应体带进断言信息，避免只看到 "Received: false"
    throw new Error(
      `发送消息失败：HTTP ${response.status()} ${response.statusText()} -> ${text.slice(0, 400)}`,
    )
  }
  return JSON.parse(text)
}

/**
 * 确保会话列表可见。
 *
 * 宽屏列表常驻，窄屏收起为浮层（入口是「会话列表」/「展开会话队列」按钮）。
 *
 * 不能用「轮询里反复点击」的写法：列表刷新（`loadConversations`）会让入口
 * 按钮在重渲染瞬间消失，轮询恰好落在这个间隙就会误判为「打不开」。
 * 因此每次尝试都走一遍明确的等待序列，并把结果累加后整体重试。
 */
export async function openConversationList(
  page: Page,
  view: 'customer' | 'support' = 'customer',
): Promise<Locator> {
  const list = page.getByRole('complementary', {
    name: view === 'customer' ? '我的售后会话' : '会话队列',
  })
  const expand = page.getByRole('button', {
    // 客户侧按钮带图标，可访问名是「unordered-list 会话列表」，
    // 精确名匹配不到，必须用子串匹配。
    name: view === 'customer' ? /会话列表/ : '展开会话队列',
  })

  let lastError = '未知原因'
  for (let attempt = 0; attempt < 6; attempt++) {
    if (await list.isVisible()) {
      return list
    }
    if ((await expand.count()) === 0) {
      lastError = '列表与展开入口都不存在'
      await page.waitForTimeout(500)
      continue
    }
    if (!(await expand.first().isVisible())) {
      // 入口在 DOM 里但不可见：多为重渲染瞬间，稍后重试
      lastError = '展开入口存在但不可见'
      await page.waitForTimeout(300)
      continue
    }

    await expand.first().click().catch((error: unknown) => {
      lastError = `点击展开入口失败：${String(error).slice(0, 120)}`
    })

    // 点击后二选一：列表出现，或入口消失（说明已经展开）
    try {
      await Promise.race([
        list.waitFor({ state: 'visible', timeout: 5_000 }),
        expand
          .first()
          .waitFor({ state: 'hidden', timeout: 5_000 })
          .catch(() => undefined),
      ])
    } catch {
      lastError = '点击后列表既未出现，入口也未消失'
    }
  }

  await expect(list, `展开会话列表失败（最后原因：${lastError}）`).toBeVisible()
  return list
}

/** 选择会话列表中标题包含指定文本的会话。 */
export async function selectConversationByTitle(
  page: Page,
  titleFragment: string,
  view: 'customer' | 'support' = 'customer',
): Promise<void> {
  const list = await openConversationList(page, view)
  const target = list.getByRole('button').filter({ hasText: titleFragment }).first()
  await expect(target).toBeVisible({ timeout: 20_000 })
  // 不要用 scrollIntoViewIfNeeded：会话列表不虚拟化，行都在 DOM 里；在
  // overflow:auto 容器上调用它会把容器滚到底，把整块对话区（含输入框与发送
  // 按钮）顶出视口——截图里表现为「发送按钮被裁掉」，实测 sendY 变成负数。
  // Playwright 的 click 自身会做必要滚动，直接点击即可。
  await target.click()
}

/** 消息列表区域：把断言限定在消息内，避免与列表标题/预览文本冲突。 */
export function messageLog(page: Page) {
  return page.getByRole('log', { name: '消息列表' })
}

/**
 * 发送按钮的可访问名。
 *
 * antd 会在两个中日韩字符之间插入空格（按钮渲染成「发 送」），
 * 因此不能用精确名 `'发送'` 匹配，必须允许中间空白。
 */
export const SEND_BUTTON = /发\s*送/

/** 在客户输入框输入并发送，等待输入框被清空。 */
export async function sendViaUi(page: Page, body: string): Promise<void> {
  const input = page.getByLabel('客户消息输入框')
  await input.fill(body)
  // 发送按钮限定在客户会话区域内，避免与客服侧同名按钮冲突
  await page
    .getByRole('region', { name: '客户会话内容' })
    .getByRole('button', { name: SEND_BUTTON })
    .click()
  await expect(input).toHaveValue('', { timeout: 30_000 })
}

/** 客服发送：按钮限定在客服对话区域内（发送前必须已接管）。 */
export async function sendAsOperator(page: Page, body: string): Promise<void> {
  const input = page.getByLabel('客服回复输入框')
  await input.fill(body)
  await page
    .getByRole('region', { name: '客服对话' })
    .getByRole('button', { name: SEND_BUTTON })
    .click()
  await expect(input).toHaveValue('', { timeout: 30_000 })
}
