/**
 * 回复建议卡（P1-3，5.4.4）。先列失败方式：
 * R1 三种风格仍上下堆叠；切换风格后正文不变。
 * R2 未核验或生成中时“采用”可点（核验通过前不可采用）。
 * R3 AI 接待中仍可采用。
 * R4 编辑后采用写入原文而不是编辑后的文本，且未标记为编辑后采用。
 * R5 改写结果未经接口校验就替换正文；改写失败后原文丢失。
 * R6 单风格重生成没有带当前风格。
 * R7 正文中有依据的片段与普通文字无区分（概念稿：金色虚线引用）。
 * R8 看不到这条建议依据了哪些工单/订单/会话；同一来源重复出现。
 * R9 风格切换不是可读的 tab（无 aria-selected），读屏无法知道当前风格。
 * R11 X-4：未核验也盖“已核验”章；核验通过后引用片段没有依次画线的序号。
 * R12 草稿模式核验未通过：仍盖“已核验”章；或看不到原因；或被禁止采用（用户反馈 8：不因核验整体拦截）。
 * R13 “已核验”章绝对定位压在风格切换上（用户反馈 10-18 #2）：章应在标题行内、风格切换之前。
 * R10 依据标签外露内部编号（conv-…、loreal-products@…#…），客服读不懂（全景方案 5.1）。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { describe, expect, it, vi } from 'vitest'
import type { ConsumerServiceAssistantView } from '../../api/client'
import { ReplyCard } from './ReplyCard'

const suggestions: ConsumerServiceAssistantView['replySuggestions'] = [
  { style: 'recommended', body: '亲，理解您着急，我来核对这笔订单。', claims: [], empathyDimensions: [
    { key: 'emotion_response', label: '情绪回应', status: 'present', reason: '' }] },
  { style: 'concise', body: '麻烦提供订单号。', claims: [], empathyDimensions: [] },
]

function mount(props: Partial<Parameters<typeof ReplyCard>[0]> = {}) {
  const handlers = { onAdopt: vi.fn(), onIgnore: vi.fn(), onRegenerate: vi.fn(),
    onRewrite: vi.fn(async () => '亲亲别着急，我马上帮您核对这笔订单～') }
  render(<ConfigProvider><ReplyCard suggestions={suggestions} adoptable automatic={false} generating={false}
    {...handlers} {...props} /></ConfigProvider>)
  return handlers
}

describe('ReplyCard', () => {
  it('R1 switches style in one card', () => {
    mount()
    expect(screen.getByText('亲，理解您着急，我来核对这笔订单。')).toBeInTheDocument()
    fireEvent.click(screen.getByText('简洁'))
    expect(screen.getByText('麻烦提供订单号。')).toBeInTheDocument()
    expect(screen.queryByText('亲，理解您着急，我来核对这笔订单。')).toBeNull()
  })
  it('R2 R3 adopt is disabled until verified, while generating, or in AI mode', () => {
    mount({ adoptable: false })
    expect(screen.getByRole('button', { name: /采用/ })).toBeDisabled()
  })
  it('R3 disabled in AI mode', () => {
    mount({ automatic: true })
    expect(screen.getByRole('button', { name: /采用/ })).toBeDisabled()
  })
  it('R4 adopts the edited text as edited', () => {
    const handlers = mount()
    fireEvent.click(screen.getByRole('button', { name: /编辑/ }))
    fireEvent.change(screen.getByRole('textbox', { name: '编辑回复建议' }), { target: { value: '改过的回复' } })
    fireEvent.click(screen.getByRole('button', { name: /采用/ }))
    expect(handlers.onAdopt).toHaveBeenCalledWith('recommended', '改过的回复', true)
  })
  it('R5 rewrite replaces only after the API returns; failure keeps the original', async () => {
    const handlers = mount({ onRewrite: vi.fn(async () => { throw new Error('改写未通过校验') }) })
    fireEvent.click(screen.getByRole('button', { name: /改写/ }))
    fireEvent.click(await screen.findByText('更温和'))
    await waitFor(() => expect(screen.getByText('亲，理解您着急，我来核对这笔订单。')).toBeInTheDocument())
    expect(handlers.onAdopt).not.toHaveBeenCalled()
  })
  it('R6 regenerates the current style only', () => {
    const handlers = mount()
    fireEvent.click(screen.getByText('简洁'))
    fireEvent.click(screen.getByRole('button', { name: '重新生成此风格' }))
    expect(handlers.onRegenerate).toHaveBeenCalledWith('concise')
  })
  it('R7 grounded spans are marked as references', () => {
    mount({ suggestions: [{ style: 'recommended', body: '亲，售后核实已经在处理，我来跟到底。',
      claims: [{ text: '售后核实已经在处理', sourceRefs: ['work_order:KOC7263722'] }], empathyDimensions: [] }] })
    const ref = screen.getByText('售后核实已经在处理')
    expect(ref).toHaveClass('yt-reply-ref')
    expect(ref).toHaveAttribute('title', '工单 KOC7263722')
  })
  it('R8 basis chips list distinct sources', () => {
    mount({ suggestions: [{ style: 'recommended', body: '好的，5 号的退款我盯着。', claims: [
      { text: '5 号的退款', sourceRefs: ['order:4812990707', 'message:S00005:m3'] },
      { text: '我盯着', sourceRefs: ['message:S00005:m9', 'work_order:KOC7263722'] }], empathyDimensions: [] }] })
    const basis = screen.getByRole('list', { name: '回复依据' })
    expect(basis).toHaveTextContent('订单 …0707')
    expect(basis).toHaveTextContent('工单 KOC7263722')
    expect(basis.textContent?.match(/本次会话/g)).toHaveLength(1)
  })
  it('R9 style switch exposes the selected tab', () => {
    mount()
    expect(screen.getByRole('tab', { name: '推荐' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('tab', { name: '简洁' }))
    expect(screen.getByRole('tab', { name: '简洁' })).toHaveAttribute('aria-selected', 'true')
  })
  it('R10 依据标签不外露内部编号，编号放悬停', () => {
    mount({ sources: [{ sourceId: 'knowledge:loreal-products@1.0.0#0015-4a91', kind: 'knowledge', subjectId: 'x',
      label: '测试温和氨基酸洁面乳', text: '' }],
    suggestions: [{ style: 'recommended', body: '这款成分温和。', claims: [
      { text: '成分温和', sourceRefs: ['knowledge:loreal-products@1.0.0#0015-4a91', 'conversation:conv-29bc32c12839'] }], empathyDimensions: [] }] })
    const basis = screen.getByRole('list', { name: '回复依据' })
    expect(basis).toHaveTextContent('商品资料 · 测试温和氨基酸洁面乳')
    expect(basis).toHaveTextContent('本次会话')
    expect(basis.textContent).not.toMatch(/conv-|loreal-products|#0015/)
    expect(screen.getByText('本次会话')).toHaveAttribute('title', 'conversation:conv-29bc32c12839')
  })
  it('R11 只有核验通过才盖已核验章，引用片段带依次序号', () => {
    const withClaims = [{ ...suggestions[0], body: '亲，订单已签收，退款三天到账。', claims: [
      { text: '订单已签收', sourceRefs: ['order:123456'] }, { text: '退款三天到账', sourceRefs: ['work_order:W1'] }] }]
    const { unmount } = render(<ConfigProvider><ReplyCard suggestions={withClaims as typeof suggestions} adoptable automatic={false}
      generating={false} onAdopt={vi.fn()} onIgnore={vi.fn()} onRegenerate={vi.fn()} onRewrite={vi.fn()} /></ConfigProvider>)
    expect(screen.getByText('已核验')).toBeInTheDocument()
    expect(screen.getByText('订单已签收').style.getPropertyValue('--i')).toBe('0')
    expect(screen.getByText('退款三天到账').style.getPropertyValue('--i')).toBe('1')
    unmount()
    mount({ adoptable: false })
    expect(screen.queryByText('已核验')).toBeNull()
  })
  it('R12 review notes show a 待确认 stamp, keep adopt enabled and hide 已核验', () => {
    const flagged = [{ ...suggestions[0], reviewNotes: ['订单状态缺少依据'] }]
    mount({ suggestions: flagged as typeof suggestions })
    expect(screen.getByLabelText('待确认：订单状态缺少依据')).toBeInTheDocument()
    expect(screen.queryByText('已核验')).toBeNull()
    expect(screen.getByRole('button', { name: /采用/ })).toBeEnabled()
  })
  it('R13 verified stamp sits in the header flow before the style tabs', () => {
    mount()
    const stamp = screen.getByText('已核验')
    const tabs = screen.getByRole('tablist', { name: '回复风格' })
    expect(stamp.parentElement).toBe(tabs.parentElement)
    expect(stamp.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
