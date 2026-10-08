/**
 * 草稿隔离测试（AC-23 / 前端规范第 5.1 节）。
 *
 * 草稿以 (conversationId, viewRole) 为键：切换会话不串草稿，
 * 同一会话的客户草稿与客服草稿互不影响。
 */
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { draftKey, useDraftStore } from './draftStore'

describe('draftKey', () => {
  it('会话与角色共同构成键', () => {
    expect(draftKey('conv-1', 'customer')).not.toBe(draftKey('conv-1', 'support'))
    expect(draftKey('conv-1', 'customer')).not.toBe(draftKey('conv-2', 'customer'))
  })
})

describe('useDraftStore', () => {
  it('不同会话的草稿互不影响', () => {
    const { result } = renderHook(() => useDraftStore())

    act(() => result.current.set('conv-1', 'customer', '会话一的草稿'))
    act(() => result.current.set('conv-2', 'customer', '会话二的草稿'))

    expect(result.current.get('conv-1', 'customer')).toBe('会话一的草稿')
    expect(result.current.get('conv-2', 'customer')).toBe('会话二的草稿')
  })

  it('同一会话的客户草稿与客服草稿互相隔离', () => {
    const { result } = renderHook(() => useDraftStore())

    act(() => result.current.set('conv-1', 'customer', '客户写的'))
    act(() => result.current.set('conv-1', 'support', '客服写的'))

    expect(result.current.get('conv-1', 'customer')).toBe('客户写的')
    expect(result.current.get('conv-1', 'support')).toBe('客服写的')
  })

  it('清除只影响目标键', () => {
    const { result } = renderHook(() => useDraftStore())

    act(() => result.current.set('conv-1', 'customer', 'a'))
    act(() => result.current.set('conv-1', 'support', 'b'))
    act(() => result.current.clear('conv-1', 'customer'))

    expect(result.current.get('conv-1', 'customer')).toBe('')
    expect(result.current.get('conv-1', 'support')).toBe('b')
  })

  it('未设置过的键返回空字符串而不是 undefined', () => {
    const { result } = renderHook(() => useDraftStore())
    expect(result.current.get('never-seen', 'customer')).toBe('')
  })

  it('snapshot 反映全部草稿，便于排查串线', () => {
    const { result } = renderHook(() => useDraftStore())
    act(() => result.current.set('conv-1', 'customer', 'x'))
    expect(result.current.snapshot()).toEqual({ 'conv-1::customer': 'x' })
  })
})
