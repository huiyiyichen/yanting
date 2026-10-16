/**
 * 情绪色号（全景方案 2.1）失败方式：
 * S1 段数不受限，长会话把色号压成细线（最多最近 6 段）。
 * S2 最新一段与其他等高，看不出“现在”的情绪（多段时最新占 40%）。
 * S3 只有颜色没有文字等价信息（aria-label 写出情绪序列与高风险）。
 * S4 高风险没有圆点；无风险也出圆点。
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EmotionSwatch, bandHeights } from './EmotionSwatch'

describe('EmotionSwatch', () => {
  it('S1/S3 最多 6 段，标签写出最近序列', () => {
    const { container } = render(<EmotionSwatch bands={['calm', 'calm', 'dissatisfied', 'angry', 'angry', 'dissatisfied', 'calm', 'calm']} />)
    expect(container.querySelectorAll('.yt-swatch-band')).toHaveLength(6)
    expect(screen.getByRole('img')).toHaveAttribute('aria-label', '不满、激烈、激烈、不满、平稳、平稳')
  })
  it('S2 最新一段 40%，其余平分 60%；一段时占满', () => {
    const hs = bandHeights(3, 54, 1.5)
    const inner = 54 - 3
    expect(hs[2]).toBeCloseTo(inner * 0.4)
    expect(hs[0]).toBeCloseTo(inner * 0.3)
    expect(bandHeights(1, 54, 1.5)).toEqual([54])
  })
  it('S4 高风险圆点与标签', () => {
    const { container, rerender } = render(<EmotionSwatch bands={['angry']} highRisk />)
    expect(container.querySelector('.yt-swatch-risk')).not.toBeNull()
    expect(screen.getByRole('img')).toHaveAttribute('aria-label', '激烈，高风险')
    rerender(<EmotionSwatch bands={['calm']} />)
    expect(container.querySelector('.yt-swatch-risk')).toBeNull()
  })
})
