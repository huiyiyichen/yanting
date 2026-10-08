import { expect, test } from '@playwright/test'

import {
  CUSTOMER,
  createConversation,
  selectConversationByTitle,
  sendCustomerMessage,
} from './helpers'

/**
 * 结束服务与评价闭环（PRD 5.2）。
 *
 * 覆盖的是**跨视角**链路：客服点「结束服务」→ 案件终结并开放评价入口 →
 * 客户视角出现 1—5 星评分 → 提交后落库为 submitted。
 *
 * 运行数据真实落库且不清理，因此正文带本次运行唯一标记（marker），
 * 标记必须在最前面，否则会话标题截断后定位不到（见 state.spec.ts 说明）。
 */

function runMarker(): string {
  return String(Date.now()).slice(-5)
}

test.describe('结束服务与评价闭环', () => {
  test('客服结束服务后，客户可提交 1—5 星评价', async ({ page }) => {
    const marker = runMarker()
    const conversationId = await createConversation(page)
    await sendCustomerMessage(
      page,
      conversationId,
      `[${marker}] 结束服务评价闭环：吸力变弱`,
      `close-rate-${marker}`,
    )

    // 客服视角：选中会话 -> 结束服务 -> 二次确认
    await page.goto('/support')
    await selectConversationByTitle(page, marker, 'support')

    const closeTrigger = page
      .getByRole('region', { name: '客服对话' })
      .getByRole('button', { name: '结束服务' })
    await expect(closeTrigger).toBeEnabled({ timeout: 20_000 })
    await closeTrigger.click()

    // Popconfirm 的确认按钮与触发按钮同名，必须限定在浮层内点击
    await page
      .locator('.ant-popconfirm')
      .getByRole('button', { name: '结束服务' })
      .click()

    await expect(page.getByRole('alert').filter({ hasText: '服务已结束' })).toBeVisible({
      timeout: 30_000,
    })
    // 终态：按钮不再可用，不会重复结束
    await expect(closeTrigger).toBeDisabled()

    const caseAfterClose = await page.request.get(
      `/api/support/conversations/${conversationId}/case`,
      { headers: { 'X-Demo-View-Role': 'support' } },
    )
    const caseBody = (await caseAfterClose.json()) as { caseStatus: string; ratingStatus: string }
    expect(caseBody.caseStatus).toBe('closed')
    expect(caseBody.ratingStatus).toBe('pending')

    // 客户视角：出现评分卡片，提交 5 分
    await page.goto('/customer')
    await selectConversationByTitle(page, marker)
    await expect(page.getByRole('region', { name: '满意度评价' })).toBeVisible({
      timeout: 20_000,
    })
    await expect(page.getByText('本次服务已结束，请为这次体验评分')).toBeVisible()

    // 五档表情按钮各自带文字标签，点第 5 档即 5 分
    const fiveStars = page.getByRole('button', { name: '评分 5 分：很满意' })
    await expect(fiveStars).toBeVisible()
    await fiveStars.click()
    await expect(page.getByText(/本次服务已评价：5 分/)).toBeVisible({ timeout: 20_000 })

    const rating = await page.request.get(`/api/customer/conversations/${conversationId}/rating`, {
      headers: CUSTOMER,
    })
    const ratingBody = (await rating.json()) as { ratingStatus: string; userRating: number | null }
    expect(ratingBody.ratingStatus).toBe('submitted')
    expect(ratingBody.userRating).toBe(5)
  })
})
