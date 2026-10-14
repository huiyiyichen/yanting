/**
 * 评测与成本面板（P1-7/P1-9）。先列失败方式：
 * P1 未配置价格时显示 ¥0（应显示“未配置价格”）。
 * P2 Mock 与真实调用混在一起展示。
 * P3 缓存命中率无数据时显示 0%。
 */
import { render, screen } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { describe, expect, it } from 'vitest'
import type { UsageView } from '../../api/client'
import { UsagePanel } from './UsagePanel'

const empty = { calls: 0, promptTokens: 0, completionTokens: 0, cachedTokens: 0, cacheHitRate: null,
  callsMissingTokens: 0, estimatedCost: null, replyRuns: 0, callsPerReply: null, costPerReply: null,
  byStage: [], byModel: [], byDay: {} }
const view: UsageView = {
  live: { ...empty, calls: 6, promptTokens: 60000, completionTokens: 3000, cachedTokens: 12000, cacheHitRate: 0.2,
    replyRuns: 3, callsPerReply: 2, byStage: [{ stage: 'draft', calls: 3, promptTokens: 40000, completionTokens: 2400, cachedTokens: 8000, latencySeconds: 12 },
      { stage: 'verify', calls: 3, promptTokens: 20000, completionTokens: 600, cachedTokens: 4000, latencySeconds: 6 }] },
  mock: { ...empty, calls: 4 },
  pricedModels: [],
}

describe('UsagePanel', () => {
  it('P1 shows missing price instead of zero', () => {
    render(<ConfigProvider><UsagePanel usage={view} /></ConfigProvider>)
    expect(screen.getAllByText('未配置价格').length).toBeGreaterThan(0)
    expect(screen.queryByText('¥0')).toBeNull()
  })
  it('P2 separates live and mock', () => {
    render(<ConfigProvider><UsagePanel usage={view} /></ConfigProvider>)
    expect(screen.getByLabelText('真实调用')).toHaveTextContent('6')
    expect(screen.getByLabelText('Mock 调用')).toHaveTextContent('4')
  })
  it('P3 cache hit rate shows a dash without data', () => {
    render(<ConfigProvider><UsagePanel usage={{ ...view, live: { ...view.live, cacheHitRate: null } }} /></ConfigProvider>)
    expect(screen.getByLabelText('缓存命中率')).toHaveTextContent('—')
  })
})
