import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

import {
  CUSTOMER,
  createConversation,
  listMessages,
  messageLog,
  openConversationList,
  selectConversationByTitle,
  sendAsOperator,
  sendCustomerMessage,
  sendViaUi,
  SUPPORT,
} from './helpers'

/** 本文件所在目录：用于读取 `fixtures/` 下的固定测试图片。 */
const HERE = dirname(fileURLToPath(import.meta.url))

/**
 * 刷新恢复与跨会话竞态回归（AC-23、AC-25、AC-29）。
 *
 * 关键原则：已发送消息以**服务端**为准；浏览器只保留偏好与未发送草稿。
 * 刷新、切换会话都不能造成重复消息或串线。
 *
 * 运行数据会真实落库且不清理，因此每个用例的内容都带本次运行唯一标记（marker）。
 * 否则「刷新恢复测试」这类固定标题会在多次运行后指向上一次的会话，
 * 断言就会落到一个状态完全不同的旧会话上——这是测试自身的缺陷，不是产品缺陷。
 */

/** 取进程启动毫秒数的后 5 位：一次运行内固定，且不易与历史数据碰撞。 */
function runMarker(): string {
  return String(Date.now()).slice(-5)
}

/**
 * 构造本次运行唯一的消息正文。
 *
 * 标记必须放在**最前面**：会话标题取自首条客户消息的前 16 个字符
 * （见 `conversation_repository.append_message`），标记放末尾会被截掉，
 * 列表里就会出现多个同名会话，定位随之落到旧数据上。
 */
function msg(base: string, marker: string): string {
  return `[${marker}] ${base}`
}

test.describe('刷新与状态恢复', () => {
  test('刷新后消息以服务端恢复，且不产生重复', async ({ page }) => {
    const marker = runMarker()
    const body = msg('刷新恢复测试：吸力变弱', marker)
    const conversationId = await createConversation(page)
    await sendCustomerMessage(page, conversationId, body, `refresh-1-${marker}`)

    await page.goto('/customer')
    await selectConversationByTitle(page, marker)

    const messagesBefore = await listMessages(page, conversationId)
    await expect(messageLog(page).getByText(body)).toBeVisible()

    await page.reload()
    await selectConversationByTitle(page, marker)
    await expect(messageLog(page).getByText(body)).toBeVisible()

    const messagesAfter = await listMessages(page, conversationId)
    // 刷新不得新增任何消息
    expect(messagesAfter.length).toBe(messagesBefore.length)
    const bodies = messagesAfter.map((item) => item.body)
    expect(bodies.filter((item) => item === body)).toHaveLength(1)
  })

  test('未发送草稿在刷新后不写入服务端', async ({ page }) => {
    const marker = runMarker()
    const anchor = msg('草稿测试锚点', marker)
    const unsent = msg('这段文字不应被发送', marker)
    const conversationId = await createConversation(page)
    await sendCustomerMessage(page, conversationId, anchor, `draft-anchor-${marker}`)

    // 助手回复是**异步**落库的：客户消息返回后 conversation 还会再追加一条
    // 助手消息。若在此刻立刻取基线，刷新后助手消息已落库，长度对比会假失败。
    // 因此等到本轮消息数稳定（连续两次读数一致）再取 before。
    let before: Awaited<ReturnType<typeof listMessages>> = []
    await expect
      .poll(
        async () => {
          const first = await listMessages(page, conversationId)
          await page.waitForTimeout(700)
          const second = await listMessages(page, conversationId)
          before = second
          return first.length === second.length && second.length > 0
        },
        { timeout: 30_000, message: '会话消息数未稳定（助手回复仍在写入）' },
      )
      .toBe(true)

    await page.goto('/customer')
    await selectConversationByTitle(page, marker)
    await page.getByLabel('客户消息输入框').fill(unsent)

    await page.reload()
    await selectConversationByTitle(page, marker)

    const after = await listMessages(page, conversationId)
    expect(after.length).toBe(before.length)
    expect(after.map((item) => item.body)).not.toContain(unsent)
  })

  test('同一幂等键重复提交不追加第二条消息', async ({ page }) => {
    const marker = runMarker()
    const body = msg('幂等键测试', marker)
    const conversationId = await createConversation(page)
    const first = await sendCustomerMessage(page, conversationId, body, `idem-key-1-${marker}`)
    const second = await sendCustomerMessage(page, conversationId, body, `idem-key-1-${marker}`)

    expect(first.message.messageId).toBe(second.message.messageId)
    // 第二次为重放：created 必须为 false
    expect(first.created).toBe(true)
    expect(second.created).toBe(false)
    const messages = await listMessages(page, conversationId)
    expect(messages.filter((item) => item.body === body)).toHaveLength(1)
  })
})

test.describe('跨会话隔离与竞态', () => {
  test('两个会话的消息与草稿都不串线（AC-23）', async ({ page }) => {
    const marker = runMarker()
    const bodyA = msg('会话A的唯一内容', marker)
    const bodyB = msg('会话B的唯一内容', marker)
    const conversationA = await createConversation(page)
    const conversationB = await createConversation(page)
    await sendCustomerMessage(page, conversationA, bodyA, `a-1-${marker}`)
    await sendCustomerMessage(page, conversationB, bodyB, `b-1-${marker}`)

    await page.goto('/customer')
    await selectConversationByTitle(page, bodyA)

    await expect(messageLog(page).getByText(bodyA)).toBeVisible()
    await expect(messageLog(page).getByText(bodyB)).toHaveCount(0)

    await selectConversationByTitle(page, bodyB)
    await expect(messageLog(page).getByText(bodyB)).toBeVisible()
    await expect(messageLog(page).getByText(bodyA)).toHaveCount(0)
  })

  test('切换会话后异步回复只回写原会话', async ({ page }) => {
    const marker = runMarker()
    const anchorA = msg('会话A锚点内容', marker)
    const anchorB = msg('会话B锚点内容', marker)
    const raceBody = msg('只在会话A里发送的竞态内容', marker)
    const conversationA = await createConversation(page)
    await sendCustomerMessage(page, conversationA, anchorA, `anchor-a-${marker}`)
    const conversationB = await createConversation(page)
    await sendCustomerMessage(page, conversationB, anchorB, `anchor-b-${marker}`)

    await page.goto('/customer')

    // 选中 A 并在 A 中发送
    await selectConversationByTitle(page, anchorA)
    await expect(messageLog(page).getByText(anchorA)).toBeVisible()
    await sendViaUi(page, raceBody)

    // 立刻切到 B，等待可能的异步回写
    await selectConversationByTitle(page, anchorB)
    await page.waitForTimeout(2000)

    const messagesA = await listMessages(page, conversationA)
    const messagesB = await listMessages(page, conversationB)
    const bBodies = messagesB.map((item) => item.body).join('\n')

    // 发送内容必须落在 A，绝不能串到 B
    expect(messagesA.map((item) => item.body)).toContain(raceBody)
    expect(bBodies).not.toContain(raceBody)
    // B 中不得出现 A 的任何回复内容
    expect(bBodies).not.toContain('会话A')
  })

  test('会话列表刷新后仍显示服务端数据', async ({ page }) => {
    const marker = runMarker()
    const body = msg('列表恢复测试内容', marker)
    const conversationId = await createConversation(page)
    await sendCustomerMessage(page, conversationId, body, `list-1-${marker}`)

    await page.goto('/customer')
    // 窄屏会话列表默认收起；本用例只验证列表刷新，不能选中会话
    // （窄屏选中后会收起浮层，刷新按钮随之消失）
    await openConversationList(page)
    const before = await listMessages(page, conversationId)

    await page.getByRole('button', { name: '刷新列表' }).click()
    await expect(page.getByRole('button', { name: body }).first()).toBeVisible()

    const after = await listMessages(page, conversationId)
    expect(after.length).toBe(before.length)
  })
})

test.describe('附件与图片', () => {
  test('上传的图片随消息发送，模型看图后回复里说出可见线索', async ({ page }) => {
    const marker = runMarker()
    const body = msg('请看我拍的面板照片，两个指示灯分别是什么颜色', marker)
    const conversationId = await createConversation(page)

    /* 用固定夹具图 `e2e/fixtures/panel-photo.png`：画着红色 POWER 灯、绿色 FILTER 灯
       与序列号 S/N 8842-XR。为什么不用现场合成的纯色块：实测纯红方块会让模型
       判不出「与故障有关的可见现象」，`observedFromImage` 为空（模型确实看了，
       但没有可复述的现象）——那样就无法用它判定「模型到底看没看见」。
       这张图的内容是 live 实测中模型确实读出来的（颜色 + 标签 + 序列号）。 */
    const png = readFileSync(resolve(HERE, 'fixtures/panel-photo.png'))
    const uploaded = await page.request.post(
      `/api/customer/conversations/${conversationId}/attachments`,
      {
        headers: CUSTOMER,
        multipart: { file: { name: 'panel.png', mimeType: 'image/png', buffer: png } },
      },
    )
    expect(
      uploaded.ok(),
      `上传失败：HTTP ${uploaded.status()} ${await uploaded.text()}`,
    ).toBeTruthy()
    const attachmentId = (await uploaded.json()).attachmentId as string

    // 取图地址必须能读回真实 PNG 字节
    const content = await page.request.get(
      `/api/customer/attachments/${attachmentId}/content`,
      { headers: CUSTOMER },
    )
    expect(content.ok()).toBeTruthy()
    expect(content.headers()['content-type']).toContain('image/png')

    /* 多模态已接通（`ANKER_AGENT_LLM_VISION_MODEL=deepseek-chat`，健康检查
       `vision: ready`）：带图发送必须成功，并且**回复里要出现只有看图才知道的内容**。
       未配置多模态时这里会是 503 provider_not_configured——那条边界由后端的
       `TestVisionBoundary` 固定，不再由 e2e 承担。 */
    const sent = await page.request.post(
      `/api/customer/conversations/${conversationId}/messages`,
      {
        headers: CUSTOMER,
        data: { body, clientMessageKey: `img-${marker}`, attachmentIds: [attachmentId] },
      },
    )
    expect(sent.status(), await sent.text()).toBe(200)
    const reply = (await sent.json()).reply.body as string
    expect(reply, `回复里没有看图线索：${reply.slice(0, 200)}`).toMatch(/红/)

    // 线索也要能被客服核对（不是只在回复里说了一句）
    const caseView = await page.request.get(
      `/api/support/conversations/${conversationId}/case`,
      { headers: SUPPORT },
    )
    const clues = ((await caseView.json()).observedFromImage ?? []) as string[]
    expect(clues.join('；')).toMatch(/红/)

    // 图片必须挂到**客户那条消息**上（不是孤儿附件）
    const messages = await listMessages(page, conversationId)
    const mine = messages.find((item) => item.body.includes(marker))
    expect(mine?.attachments?.length).toBe(1)
    expect(String(mine?.attachments?.[0]?.url)).toContain(`/attachments/${attachmentId}/content`)
  })

  test('图片消息在气泡内渲染出可访问的图片元素', async ({ page }) => {
    const conversationId = await createConversation(page)
    const png = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEX///+/v7+jQ3Y5AAAADklEQVQI12P4AIX8EAgALgAD/aNpbtEAAAAASUVORK5CYII=',
      'base64',
    )
    // 上传后**直接**把附件挂到消息上（不经过带图发送）：带图发送在未配置多模态时
    // 会如实 503，而这里要验证的是「附件挂上之后能不能显示」。
    // 说明：渲染单元测试在 `MessageList.test.tsx` 里用 mock 数据覆盖，
    // 这里只确认取图地址在浏览器里真的能加载出 PNG。
    const uploaded = await page.request.post(
      `/api/customer/conversations/${conversationId}/attachments`,
      {
        headers: CUSTOMER,
        multipart: { file: { name: 'fault.png', mimeType: 'image/png', buffer: png } },
      },
    )
    const attachmentId = (await uploaded.json()).attachmentId as string

    // 必须先打开页面再用相对地址取图：`page.evaluate` 在 about:blank 上执行时
    // 相对 URL 无法解析（实测报 `Failed to parse URL from /api/...`）。
    await page.goto('/customer')

    // 用真实 <img> 加载而不是 fetch：fetch 成功只说明字节被取回，
    // 图片损坏时它照样 200；<img> 的 load 事件才证明浏览器能解码。
    const decoded = await page.evaluate(async (url) => {
      const image = new Image()
      const settled = new Promise<{ ok: boolean; width: number; height: number }>((resolve) => {
        image.onload = () => resolve({ ok: true, width: image.naturalWidth, height: image.naturalHeight })
        image.onerror = () => resolve({ ok: false, width: 0, height: 0 })
      })
      image.src = url
      document.body.appendChild(image)
      return settled
    }, `/api/customer/attachments/${attachmentId}/content`)

    expect(decoded.ok).toBe(true)
    // 上传的是 8×8 PNG，解码尺寸必须一致（取错了图或返回占位图都会在这里失败）
    expect(decoded.width).toBe(8)
    expect(decoded.height).toBe(8)
  })
})

test.describe('托管与候选竞态', () => {
  test('托管期间客服不能发送，接管后可发送', async ({ page }) => {
    const marker = runMarker()
    const body = msg('接管流程测试', marker)
    const conversationId = await createConversation(page)
    await sendCustomerMessage(page, conversationId, body, `tk-1-${marker}`)

    await page.goto('/support')
    // 不用「等队列可见」做前置：窄屏队列默认收起为浮层，
    // selectConversationByTitle 会自己等到入口出现并展开。
    await selectConversationByTitle(page, marker, 'support')

    // 先等待队列与案件加载完成（托管状态来自服务端），再断言不变量：
    // 托管中 → 输入禁用且给出「需先接管」提示
    await expect(page.getByText('AI 托管中')).toBeVisible({ timeout: 15_000 })
    const input = page.getByLabel('客服回复输入框')
    await expect(input).toBeDisabled()
    await expect(page.getByText(/发送前请先/)).toBeVisible()

    await page.getByRole('button', { name: '接管会话' }).click()
    await expect(input).toBeEnabled({ timeout: 15_000 })

    await sendAsOperator(page, '您好，我是客服，正在为您处理')

    await expect
      .poll(
        async () => {
          const messages = await listMessages(page, conversationId, 'support')
          return messages.filter((item) => item.senderRole === 'operator').length
        },
        { timeout: 20_000 },
      )
      .toBe(1)

    // 服务端记录的模式已切换
    const queue = await page.request.get('/api/support/queue', { headers: SUPPORT })
    const items = (await queue.json()) as { conversationId: string; serviceMode: string }[]
    const target = items.find((item) => item.conversationId === conversationId)
    expect(target?.serviceMode).toBe('operator_assisted')
  })

  test('新客户消息使旧候选过期（AC-25）', async ({ page }) => {
    const marker = runMarker()
    const conversationId = await createConversation(page)
    await sendCustomerMessage(page, conversationId, msg('候选过期测试：吸力弱', marker), `exp-1-${marker}`)

    const generated = await page.request.post(
      `/api/support/conversations/${conversationId}/suggestions/generate`,
      { headers: SUPPORT },
    )
    expect(generated.ok()).toBeTruthy()
    expect((await generated.json()).expires).toBe(false)

    // 客户追问。AI 回复是异步落库的：currentRevision 会从 3（客户消息）
    // 走到 4（助手回复）。直接读一次会在 3 的瞬间拿到未过期的中间态，
    // 因此轮询到终态再断言，而不是假设回复已经写完。
    await sendCustomerMessage(
      page,
      conversationId,
      msg('补充：还在保修期内吗', marker),
      `exp-2-${marker}`,
    )

    type SuggestionPayload = {
      expires: boolean
      messageRevision: number
      currentRevision: number
      items: { messageRevision: number; expires: boolean }[]
    }
    let payload: SuggestionPayload | null = null
    // 轮询到「会话版本已推进且候选已过期」这一稳定终态。
    // 不断言具体的 revision 数值：候选在追问后可能被重新生成或被清理，
    // 数值会随实现变化；AC-25 要求的是**旧候选不可再直接发送**这一不变量。
    await expect
      .poll(
        async () => {
          const after = await page.request.get(
            `/api/support/conversations/${conversationId}/suggestions`,
            { headers: SUPPORT },
          )
          payload = (await after.json()) as SuggestionPayload
          return payload.currentRevision > 2 && payload.expires === true
        },
        { timeout: 20_000, message: '客户追问后候选未进入「已过期」终态' },
      )
      .toBe(true)

    expect(payload).not.toBeNull()
    // 候选整体过期
    expect(payload?.expires).toBe(true)
    // 会话版本确实因新消息推进
    expect(payload?.currentRevision).toBeGreaterThan(payload?.messageRevision ?? 0)
    // 每一条候选都带 expires=true，不存在仍可直接发送的候选
    expect(payload?.items.every((item) => item.expires)).toBe(true)
  })
})
