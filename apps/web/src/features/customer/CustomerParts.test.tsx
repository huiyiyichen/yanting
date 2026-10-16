/**
 * 客户页拆分（P2-2）。
 * C1 拆分后评价状态文案丢失或错位（已评分/未评分/待评价）；
 * C2 未请求评价时仍出现评价行；
 * C3 评价卡打开时同时出现结果行。
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ServiceRating, ratingText } from './CustomerParts'

describe('ServiceRating', () => {
  it('三种结果文案', () => {
    expect(ratingText({ status: 'submitted', value: 5 })).toBe('本次服务已评价：5 分，感谢反馈')
    expect(ratingText({ status: 'skipped', value: null })).toBe('本次服务已结束（未评分）')
    expect(ratingText({ status: 'pending', value: null })).toBe('待评价')
  })
  it('未请求时不渲染', () => {
    expect(ratingText({ status: 'not_requested', value: null })).toBeNull()
    expect(ratingText(null)).toBeNull()
  })
  it('评价卡打开时不显示结果行', () => {
    render(<ServiceRating open busy={false} rating={{ status: 'submitted', value: 4 }} onSubmit={() => {}} />)
    expect(screen.queryByText(/已评价/)).toBeNull()
  })
})
