/**
 * 风险队列迷你声纹。
 * F1 客服回复画成情绪柱（应为金点）；F2 档位颜色/高度错位；F3 空序列仍画空 svg 占位。
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { RiskSpark } from './RiskSpark'

describe('RiskSpark', () => {
  it('消费者为情绪柱、客服为点，档位决定颜色与高度', () => {
    const { container } = render(<RiskSpark seq={['c0', 'o', 'c2', 'o', 'c1']} />)
    expect(screen.getByRole('img', { name: '情绪序列：平稳、不满、激烈各 1 次' })).toBeInTheDocument()
    const bars = container.querySelectorAll('rect')
    expect(bars).toHaveLength(3)
    expect(container.querySelectorAll('circle')).toHaveLength(2)
    expect([...bars].map((bar) => bar.getAttribute('class'))).toEqual(['is-calm', 'is-angry', 'is-dissatisfied'])
    expect(Number(bars[1].getAttribute('height'))).toBeGreaterThan(Number(bars[2].getAttribute('height')))
  })
  it('没有序列不渲染', () => {
    const { container } = render(<RiskSpark seq={[]} />)
    expect(container.querySelector('svg')).toBeNull()
  })
})
