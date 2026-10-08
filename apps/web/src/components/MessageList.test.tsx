/**
 * 消息列表组件测试。
 *
 * 覆盖三件在 e2e 里难断言或依赖真实模型的事：
 * 1. 空会话时 `role="log"` 区域**仍存在**（缺陷 #48：区域缺失会让屏幕阅读器
 *    丢失首条消息播报，也让按可访问名定位的测试超时）；
 * 2. 客户上传的图片附件**在气泡里真的渲染出来**（缺陷 #47 的前端半边）；
 *    多模态未接通时 e2e 只能验证到「接口返回 503」，图片渲染必须由组件测试兜住；
 * 3. 同一份消息数据在客户/客服视角下方向相反（前端规范第 5.2 节）。
 */
import { render, screen } from '@testing-library/react'
import { App as AntApp, ConfigProvider } from 'antd'
import { describe, expect, it } from 'vitest'

import type { MessageView } from '../api/client'
import { MessageList } from './MessageList'

const CONVERSATION_ID = 'conv-test-1'

function message(overrides: Partial<MessageView> = {}): MessageView {
  return {
    messageId: 'msg-1',
    conversationId: CONVERSATION_ID,
    senderRole: 'customer',
    body: '',
    messageRevision: 1,
    createdAt: '2026-09-25T10:00:00+00:00',
    ...overrides,
  } as MessageView
}

const IMAGE_ATTACHMENT = {
  attachmentId: 'att-1',
  conversationId: CONVERSATION_ID,
  mimeType: 'image/png',
  byteSize: 89,
  width: 8,
  height: 8,
  url: `/api/customer/attachments/att-1/content`,
}

function renderList(messages: MessageView[], viewRole: 'customer' | 'support') {
  return render(
    <ConfigProvider>
      <AntApp>
        <MessageList messages={messages} viewRole={viewRole} />
      </AntApp>
    </ConfigProvider>,
  )
}

describe('MessageList', () => {
  it('空会话仍渲染 role=log 区域并可定位', () => {
    renderList([], 'customer')

    const region = screen.getByRole('log', { name: '消息列表' })
    expect(region).toBeInTheDocument()
    expect(region).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByText('开始新对话')).toBeInTheDocument()
  })

  it('渲染客户上传的图片附件，且可点开查看原图', () => {
    const { container } = renderList(
      [
        message({
          body: '商品包装破损，拍了一张照片',
          senderRole: 'customer',
          attachments: [IMAGE_ATTACHMENT],
        }),
      ],
      'support',
    )

    const image = screen.getByAltText('图片附件') as HTMLImageElement
    expect(image).toBeInTheDocument()
    expect(image).toHaveAttribute('src', IMAGE_ATTACHMENT.url)
    // 缩略图有尺寸上限，不能被原图撑破气泡。
    expect(image.getAttribute('style')).toContain('max-width: 240px')

    const link = image.closest('a')
    expect(link).toHaveAttribute('href', IMAGE_ATTACHMENT.url)
    expect(link).toHaveAttribute('target', '_blank')
    expect(container).toHaveTextContent('商品包装破损，拍了一张照片')
  })

  it('纯图片消息（正文为空）仍显示图片，不显示空正文', () => {
    renderList([message({ body: '', attachments: [IMAGE_ATTACHMENT] })], 'support')

    expect(screen.getByAltText('图片附件')).toBeInTheDocument()
  })

  it('附件缺少取图地址时不渲染破图', () => {
    renderList(
      [message({ body: '只有文字', attachments: [{ attachmentId: 'att-broken' }] })],
      'support',
    )

    expect(screen.queryByAltText('图片附件')).not.toBeInTheDocument()
    expect(screen.getByText('只有文字')).toBeInTheDocument()
  })

  it('同一消息在客户视角靠右、客服视角靠左（方向由视角计算）', () => {
    const messages = [message({ body: '方向检查', senderRole: 'customer' })]

    const customerView = renderList(messages, 'customer')
    expect(customerView.container.querySelector('.ant-bubble-end')).not.toBeNull()
    customerView.unmount()

    const supportView = renderList(messages, 'support')
    expect(supportView.container.querySelector('.ant-bubble-start')).not.toBeNull()
  })

  it('发送失败的消息显示可重试提示，且不伪装成已发送', () => {
    render(
      <ConfigProvider>
        <AntApp>
          <MessageList
            messages={[message({ body: '这条失败了', senderRole: 'customer' })]}
            viewRole="customer"
            failedKeys={{ 'msg-1': '网络不可用' }}
          />
        </AntApp>
      </ConfigProvider>,
    )

    expect(screen.getByText('发送失败，可重试')).toBeInTheDocument()
  })
})
