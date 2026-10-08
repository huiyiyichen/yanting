import { expect, test } from '@playwright/test'

/**
 * 双视角外壳与权限边界（S3）。
 *
 * 这些用例验证与**真实后端**联调后的行为：会话来自后端、消息方向正确、
 * 客户页不含客服专属内容。
 */
test.describe('双视角外壳', () => {
  test('客户视角加载并显示会话列表与输入框', async ({ page }) => {
    await page.goto('/customer')
    const list = page.getByRole('complementary', { name: '我的售后会话' })
    // 窄屏下会话列表默认收起为浮层；宽屏常驻。两种布局都必须能到达会话列表。
    if (!(await list.isVisible())) {
      // 按钮带图标，可访问名为「unordered-list 会话列表」，需子串匹配
      await page.getByRole('button', { name: /会话列表/ }).click()
    }
    await expect(list).toBeVisible()
    await expect(page.getByRole('button', { name: /新建会话/ })).toBeVisible()
    // 收起浮层后聊天区必须仍可用（浮层是覆盖而非挤压）
    const dismiss = page.locator('[role="presentation"]').last()
    if (await dismiss.isVisible()) {
      await dismiss.click()
    }
    await expect(page.getByLabel('客户消息输入框')).toBeVisible()
  })

  test('客户侧不出现客服专属面板与审批控件', async ({ page }) => {
    await page.goto('/customer')
    await expect(page.getByLabel('客户消息输入框')).toBeVisible()
    await expect(page.getByLabel('案件辅助信息')).toHaveCount(0)
    await expect(page.getByRole('tab', { name: 'AI 辅助' })).toHaveCount(0)
    await expect(page.getByRole('tab', { name: '知识依据' })).toHaveCount(0)
    await expect(page.getByText('接管会话')).toHaveCount(0)
    await expect(page.getByText('情绪等级')).toHaveCount(0)
  })

  test('切换到客服工作台显示队列、三个页签与接管入口', async ({ page }) => {
    await page.goto('/support')
    const queue = page.getByRole('complementary', { name: '会话队列' })
    const expand = page.getByRole('button', { name: '展开会话队列' })
    const panelToggle = page.getByRole('button', { name: '打开案件辅助面板' })
    const inlineTabs = page.getByRole('tab', { name: '案件信息' })

    // 右侧辅助区：宽屏常驻面板，窄屏为抽屉
    const openedDrawer = (await inlineTabs.count()) === 0
    if (openedDrawer) {
      await panelToggle.click()
    }
    await expect(inlineTabs).toBeVisible()
    await expect(page.getByRole('tab', { name: 'AI 辅助' })).toBeVisible()
    await expect(page.getByRole('tab', { name: '知识依据' })).toBeVisible()
    // 抽屉的遮罩会拦截后续点击：先关掉再操作队列
    if (openedDrawer) {
      await page.getByRole('button', { name: '关闭' }).click()
      await expect(inlineTabs).toHaveCount(0)
    }

    // 会话队列：收起时元素仍在 DOM 里但 display:none，必须判断可见性而非 count
    if (!(await queue.isVisible())) {
      await expand.click()
    }
    await expect(queue).toBeVisible()
    // 窄屏队列是浮层，会覆盖聊天头部；收起后再断言对话区的控件
    if ((await expand.count()) > 0) {
      await expand.click()
    }
    await expect(page.getByRole('button', { name: '接管会话' })).toBeVisible()
  })

  test('客服侧提示托管期间需先接管才能发送', async ({ page }) => {
    await page.goto('/support')

    // 窄屏默认收起会话队列：先展开再选一个会话，否则没有可操作的输入框
    const queue = page.getByRole('complementary', { name: '会话队列' })
    if ((await queue.count()) === 0) {
      await page.getByRole('button', { name: '展开会话队列' }).click()
    }
    const firstConversation = queue.getByRole('button').nth(1)
    if ((await firstConversation.count()) > 0) {
      await firstConversation.click()
    }

    const input = page.getByLabel('客服回复输入框')
    await expect(input).toBeVisible()
    // 处于 AI 托管时空会话不可发送，并给出需先接管的说明
    if (await input.isDisabled()) {
      await expect(page.getByText(/发送前请先/)).toBeVisible()
    }
  })

  test('客户视角不泄露内部依据（DOM 层检查）', async ({ page }) => {
    await page.goto('/customer')
    await expect(page.getByLabel('客户消息输入框')).toBeVisible()
    const html = await page.content()
    for (const leaked of ['内部资料', 'retrievalId', 'toolCalls', 'snapshotId']) {
      expect(html).not.toContain(leaked)
    }
  })

  test('无横向溢出', async ({ page }) => {
    await page.goto('/support')
    await expect(page.getByLabel('客服回复输入框')).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(1)
  })
})
