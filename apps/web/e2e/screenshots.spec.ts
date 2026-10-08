import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

import { createConversation, selectConversationByTitle, sendCustomerMessage } from './helpers'

/**
 * 截图证据：前端规范第 8 节要求运行后检查 1440x900、1280x800 与至少一个手机尺寸，
 * 并检查文字溢出、消息方向、遮挡、错误态与图片显示。
 *
 * **每个用例自己造数据**（先建会话、再发一条真实客户消息）。原因：e2e 已改为
 * 隔离库运行（`scripts/run_e2e.ps1`，每次一个干净库），本文件按字母序**最先**执行，
 * 库里当时是空的——早期版本依赖「已有会话」挑一个来截图，隔离化之后就静默变成
 * 空态截图（断言只看可见性，看不出内容已经退化），而台账/验收表还写着「真实数据：
 * 客户消息在左、服务方在右、案件信息含型号/国家/渠道」。证据文件与描述不符属于
 * 虚假证据，因此改为自造数据。
 *
 * 只在 desktop-1440x900 这个 project 下运行，视口由用例内部显式设置，
 * 避免同一份截图被三个 project 重复覆盖。
 *
 * 运行：npx playwright test e2e/screenshots.spec.ts --project=desktop-1440x900
 * 产物：code/docs/test-cases/screenshots/
 */
const HERE = dirname(fileURLToPath(import.meta.url))
const OUTPUT_DIR = resolve(HERE, '../../../docs/test-cases/screenshots')

const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1280x800', width: 1280, height: 800 },
  { name: '390x844', width: 390, height: 844 },
]

/** 本次运行的唯一标记：会话标题取首条客户消息前 16 字，标记必须放最前面。 */
function runMarker(): string {
  return String(Date.now()).slice(-5)
}

/**
 * 造一条「有内容」的会话：客户描述故障 → Agent 真实回复（走真实模型与索引）。
 *
 * 消息方向、案件面板字段（型号/国家/渠道）与知识依据都来自这条数据，
 * 截图才有可核对的内容。等助手回复落库后再截图，避免截到空对话。
 */
async function seedConversation(page: import('@playwright/test').Page, marker: string) {
  const conversationId = await createConversation(page)
  await sendCustomerMessage(
    page,
    conversationId,
    `[${marker}] A1 Pro 无线吸尘器吸力变弱，中国大陆官网购买，怎么排查？`,
    `shot-${marker}`,
  )
  await expect
    .poll(
      async () => {
        const response = await page.request.get(
          `/api/customer/conversations/${conversationId}/messages`,
          { headers: { 'X-Demo-View-Role': 'customer' } },
        )
        const messages = (await response.json()) as { senderRole: string }[]
        return messages.some((item) => item.senderRole === 'assistant')
      },
      { timeout: 30_000, message: '助手回复未在 30 秒内落库' },
    )
    .toBe(true)
  return conversationId
}

test.describe('布局截图证据', () => {
  test.skip(
    ({ viewport }) => viewport !== null && viewport.width !== 1440,
    '截图只在 desktop-1440x900 project 下生成一次，视口由用例内部控制',
  )

  for (const viewport of VIEWPORTS) {
    test(`客户视角 @ ${viewport.name}`, async ({ page }) => {
      mkdirSync(OUTPUT_DIR, { recursive: true })
      const marker = runMarker()
      await seedConversation(page, marker)

      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.goto('/customer')
      // 客户侧根区域在窄屏时列表默认收起，因此断言聊天区而不是列表
      await expect(page.getByRole('region', { name: '客户会话内容' })).toBeVisible()
      // 选中刚造的会话，让截图展示真实消息与方向（客户在右、服务方在左）
      await selectConversationByTitle(page, marker, 'customer')
      await expect(page.getByRole('log', { name: '消息列表' })).toContainText(marker)
      // 窄屏选中会话后列表会收起，避免浮层遮住聊天区
      await page.waitForTimeout(800)
      await page.screenshot({
        path: resolve(OUTPUT_DIR, `customer-${viewport.name}.png`),
        fullPage: false,
      })
    })

    test(`客服工作台 @ ${viewport.name}`, async ({ page }) => {
      mkdirSync(OUTPUT_DIR, { recursive: true })
      const marker = runMarker()
      await seedConversation(page, marker)

      await page.setViewportSize({ width: viewport.width, height: viewport.height })
      await page.goto('/support')
      // 选刚造的会话：右侧面板会展示真实的案件信息（型号/国家/渠道/命中状态）
      await selectConversationByTitle(page, marker, 'support')
      await page.waitForTimeout(1200)
      /* 窄屏浮层会盖住聊天区，截图必须是「可操作」状态而不是被遮住的状态。
         注意不能去点「展开会话队列」——窄屏选中会话后浮层**已经自动收起**，
         那一下点击反而会把浮层重新打开（上一版截图就是这样被遮住的）。
         正确做法：若浮层此刻仍可见，用面板内的收起按钮收起，并断言它确实收起了。 */
      if (viewport.width < 820) {
        const collapse = page.getByRole('button', { name: '收起会话队列' })
        if (await collapse.isVisible().catch(() => false)) {
          await collapse.click()
          await page.waitForTimeout(400)
        }
        await expect(page.getByRole('complementary', { name: '会话队列' })).toBeHidden()
      }
      await expect(page.getByRole('region', { name: '客服对话' })).toBeVisible()
      await expect(page.getByRole('region', { name: '客服对话' })).toContainText(marker)
      // 截图必须证明输入区可用：发送按钮要在视口内，否则「可操作状态」是假的
      const sendButton = page
        .getByRole('region', { name: '客服对话' })
        .getByRole('button', { name: /发\s*送/ })
      await expect(sendButton).toBeVisible()
      const inViewport = await sendButton.evaluate((el) => {
        const rect = el.getBoundingClientRect()
        return rect.top >= 0 && rect.bottom <= window.innerHeight
      })
      expect(inViewport, '发送按钮必须落在视口内（输入区可用）').toBe(true)
      await page.screenshot({
        path: resolve(OUTPUT_DIR, `support-${viewport.name}.png`),
        fullPage: false,
      })
    })
  }
})
