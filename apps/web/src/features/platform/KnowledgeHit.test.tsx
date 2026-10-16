/**
 * 知识检索结果（P2-3）。
 * K1 只有摘录没有相关度，运营分不清强命中与凑数命中；
 * K2 相关度来源混用：有精排分时必须用精排分，没有时才按融合分相对最高分归一，不能把融合分当绝对值；
 * K3 片段全文看不到，或展开后显示的不是该片段；
 * K4 后端缺全文时仍出现“全文”按钮。
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { KnowledgeHit, hitRelevance } from './KnowledgeHit'

const hit = (patch: Record<string, unknown> = {}) => ({
  chunk_id: 'c1', document_title: '小蜜罐水乳', quoted_excerpt: '先水后乳…', source_locator: '第 2 段',
  rrf_score: 0.02, rerank_score: null, ...patch,
}) as never

describe('hitRelevance', () => {
  it('有精排分用精排分', () => { expect(hitRelevance(hit({ rerank_score: 0.83 }), [hit({ rerank_score: 0.83 })])).toBeCloseTo(0.83) })
  it('无精排分按融合分相对最高分', () => {
    const all = [hit({ rrf_score: 0.04 }), hit({ rrf_score: 0.02 })]
    expect(hitRelevance(all[1], all)).toBeCloseTo(0.5)
    expect(hitRelevance(all[0], all)).toBeCloseTo(1)
  })
})

describe('KnowledgeHit', () => {
  it('显示相关度条并可展开该片段全文', () => {
    render(<KnowledgeHit evidence={hit({ rerank_score: 0.6 })} relevance={0.6} fullText="先水后乳，早晚各一次。避开眼周。" />)
    expect(screen.getByRole('meter', { name: '相关度' })).toHaveAttribute('aria-valuenow', '60')
    expect(screen.queryByText(/避开眼周/)).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '全文' }))
    expect(screen.getByText(/避开眼周/)).toBeInTheDocument()
  })
  it('缺全文时不显示全文按钮', () => {
    render(<KnowledgeHit evidence={hit()} relevance={1} />)
    expect(screen.queryByRole('button', { name: '全文' })).toBeNull()
  })
})
