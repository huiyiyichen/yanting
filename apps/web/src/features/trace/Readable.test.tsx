/** 反馈 10-19 #4：检查器产物默认可读——模型输入按角色分段、回复画成气泡、空字段不显示。 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Readable } from './SpanInspector'

describe('Readable', () => {
  it('R1 对话按角色、回复成气泡、空字段隐藏', () => {
    render(<>
      <Readable value={JSON.stringify([{ role: 'system', content: '你是核验步骤' }, { role: 'user', content: '{"回复":"x"}' }])} />
      <Readable value={{ 回复: [{ style: 'recommended', body: '亲，已经在打包啦' }], 问题: [], 商品: ['洁面乳'] }} />
    </>)
    expect(screen.getByText('系统提示')).toBeInTheDocument()
    expect(screen.getByText('输入资料')).toBeInTheDocument()
    expect(screen.getByText('亲，已经在打包啦')).toBeInTheDocument()
    expect(screen.getByText('推荐')).toBeInTheDocument()
    expect(screen.queryByText('问题')).toBeNull()
    expect(screen.getByText('洁面乳')).toBeInTheDocument()
  })
})
