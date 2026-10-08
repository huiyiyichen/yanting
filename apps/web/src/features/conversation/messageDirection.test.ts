/**
 * 消息方向测试（前端规范第 5.2 节）。
 *
 * 这是易错点：方向必须由 senderRole + viewRole 计算，不能按数组位置推断，
 * 也不能在切换视角时翻转数据本身。
 */
import { describe, expect, it } from 'vitest'

import {
  conversationTitleFrom,
  isOwnMessage,
  messageSide,
  newClientMessageKey,
  senderLabel,
  type SenderRole,
} from './messageDirection'

const ALL_ROLES: SenderRole[] = ['customer', 'assistant', 'operator', 'system']

describe('messageSide', () => {
  it('客户视角：客户在右，服务方在左', () => {
    expect(messageSide('customer', 'customer')).toBe('end')
    expect(messageSide('assistant', 'customer')).toBe('start')
    expect(messageSide('operator', 'customer')).toBe('start')
  })

  it('客服视角：客户在左，服务方在右', () => {
    expect(messageSide('customer', 'support')).toBe('start')
    expect(messageSide('assistant', 'support')).toBe('end')
    expect(messageSide('operator', 'support')).toBe('end')
  })

  it('系统通知在两个视角都居中', () => {
    expect(messageSide('system', 'customer')).toBe('center')
    expect(messageSide('system', 'support')).toBe('center')
  })

  it('Agent 自动回复视为服务方，不算客户消息', () => {
    expect(messageSide('assistant', 'support')).toBe(messageSide('operator', 'support'))
    expect(messageSide('assistant', 'customer')).toBe(messageSide('operator', 'customer'))
  })

  it('客户与服务方在两个视角都相反', () => {
    for (const view of ['customer', 'support'] as const) {
      const customer = messageSide('customer', view)
      const service = messageSide('operator', view)
      expect(customer).not.toBe(service)
    }
  })

  it('切换视角只改变渲染方向，不改变发送者集合', () => {
    // 同一批消息在两种视角下的发送者完全一致，仅 side 互换
    for (const role of ALL_ROLES) {
      if (role === 'system') {
        continue
      }
      const inCustomerView = messageSide(role, 'customer')
      const inSupportView = messageSide(role, 'support')
      expect(inCustomerView).not.toBe(inSupportView)
    }
  })
})

describe('isOwnMessage', () => {
  it('客服视角下客服与 Agent 都算我方', () => {
    expect(isOwnMessage('operator', 'support')).toBe(true)
    expect(isOwnMessage('assistant', 'support')).toBe(true)
    expect(isOwnMessage('customer', 'support')).toBe(false)
  })

  it('客户视角下只有客户算我方', () => {
    expect(isOwnMessage('customer', 'customer')).toBe(true)
    expect(isOwnMessage('assistant', 'customer')).toBe(false)
    expect(isOwnMessage('operator', 'customer')).toBe(false)
  })
})

describe('senderLabel', () => {
  it('每个发送者都有中文展示名', () => {
    for (const role of ALL_ROLES) {
      expect(senderLabel(role)).toBeTruthy()
    }
  })
})

describe('newClientMessageKey', () => {
  it('每次生成都不同，保证幂等键唯一', () => {
    const keys = new Set(Array.from({ length: 50 }, () => newClientMessageKey()))
    expect(keys.size).toBe(50)
  })

  it('带 web- 前缀，便于与后端生成的消息区分', () => {
    expect(newClientMessageKey().startsWith('web-')).toBe(true)
  })
})

describe('conversationTitleFrom', () => {
  it('取前 16 个字符', () => {
    const text = '我的 S1 Pro 吸力不行了还漏水，能退款吗？'
    expect(conversationTitleFrom(text)).toHaveLength(16)
    expect(conversationTitleFrom(text)).toBe(text.slice(0, 16))
  })

  it('空文本返回默认标题', () => {
    expect(conversationTitleFrom('   ')).toBe('新会话')
  })
})
