import { expect, test } from '@playwright/test'

import { CUSTOMER, createConversation, selectConversationByTitle } from './helpers'

/**
 * 新会话开场白与快捷入口（用户 2026-09-26 要求）。
 *
 * 覆盖三件事：
 * 1. 新会话自带一条**固定开场白**（服务方消息，刷新后仍在）；
 * 2. 开场白下面有**可点击的快捷选项**，点了会当作客户消息发出去并得到回复；
 * 3. 用户**不点**、直接打字同样能正常走流程（快捷入口随之消失，不残留）。
 *
 * 定位方式：建会话时显式给一个带运行标记的标题。客户说话前标题是「新会话」，
 * 若按"列表第一条"定位，两个用例的 `updated_at` 落在同一秒时排序会退化，
 * 点到的可能是上一个用例的会话（首跑就是这样失败的，属测试自身缺陷）。
 */

function runMarker(): string {
  return String(Date.now()).slice(-5)
}

/** 轮询服务方消息条数：快捷点击与直接输入都应换来一次真实回复。 */
async function assistantCount(
  page: import('@playwright/test').Page,
  conversationId: string,
): Promise<number> {
  const response = await page.request.get(
    `/api/customer/conversations/${conversationId}/messages`,
    { headers: CUSTOMER },
  )
  const rows = (await response.json()) as { senderRole: string }[]
  return rows.filter((item) => item.senderRole === 'assistant').length
}

test.describe('新会话开场白与快捷入口', () => {
  test('开场白固定，快捷选项可点击并得到回复', async ({ page }) => {
    const marker = runMarker()
    const conversationId = await createConversation(page, 'CUST-DEMO-01', `[${marker}] 开场白用例`)

    // 新会话立刻带一条服务方开场白（不用等客户先说话）
    const messages = await page.request.get(
      `/api/customer/conversations/${conversationId}/messages`,
      { headers: CUSTOMER },
    )
    const list = (await messages.json()) as { senderRole: string; body: string }[]
    expect(list).toHaveLength(1)
    expect(list[0].senderRole).toBe('assistant')
    expect(list[0].body).toContain('安克智能客服')

    await page.goto('/customer')
    await selectConversationByTitle(page, marker)

    const quick = page.getByRole('button', { name: '吸力变弱怎么排查' })
    await expect(quick).toBeVisible({ timeout: 20_000 })
    await quick.click()

    // 点击＝发一条客户消息：快捷入口消失，且拿到服务方回复
    await expect(quick).toBeHidden({ timeout: 30_000 })
    await expect
      .poll(() => assistantCount(page, conversationId), { timeout: 90_000 })
      .toBeGreaterThanOrEqual(2)

    const after = await page.request.get(
      `/api/customer/conversations/${conversationId}/messages`,
      { headers: CUSTOMER },
    )
    const rows = (await after.json()) as { senderRole: string; body: string }[]
    expect(rows.some((item) => item.senderRole === 'customer')).toBe(true)
  })

  test('不点快捷选项直接打字也能正常走流程', async ({ page }) => {
    const marker = runMarker()
    const conversationId = await createConversation(page, 'CUST-DEMO-01', `[${marker}] 直接输入用例`)

    await page.goto('/customer')
    await selectConversationByTitle(page, marker)

    // 快捷入口在，但用户选择直接输入
    await expect(page.getByRole('button', { name: '吸力变弱怎么排查' })).toBeVisible({
      timeout: 20_000,
    })
    const input = page.getByLabel('客户消息输入框')
    await input.fill('滤芯多久需要更换一次？')
    await page
      .getByRole('region', { name: '客户会话内容' })
      .getByRole('button', { name: /发\s*送/ })
      .click()
    await expect(input).toHaveValue('', { timeout: 30_000 })

    await expect
      .poll(() => assistantCount(page, conversationId), { timeout: 90_000 })
      .toBeGreaterThanOrEqual(2)

    // 有客户消息后快捷入口不再显示（不会一直挂在聊天里）
    await expect(page.getByRole('button', { name: '吸力变弱怎么排查' })).toBeHidden()
  })
})
