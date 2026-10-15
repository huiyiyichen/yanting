/**
 * 商品卡（P1-4）。先列失败方式：
 * T1 消息内商品卡缺名称或图片，或带出实付、状态等内部信息。
 * T2 客户选择商品后发送的不是 SKU/订单号（携带名称、图片等可伪造字段）。
 * T3 客服顶部商品卡缺实付、订单号、状态、承运商与城市；无来源时仍渲染空卡。
 * T4 点击顶部商品卡不能打开档案中的对应订单。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { customerApi, supportApi } from '../api/client'
import { DeskProductCard } from '../features/service-desk/DeskProductCard'
import { ProductCardBubble, ProductPicker } from './ProductCard'

const card = { source: 'catalog' as const, sku: 'LRLWX26013', name: '欧莱雅金致小蜜罐4.0水乳套装', imageUrl: 'https://img/x.png' }

describe('ProductCard', () => {
  it('T1 bubble shows identity only', () => {
    const { container } = render(<ProductCardBubble card={{ ...card, orderId: '692094' }} />)
    expect(screen.getByText(card.name)).toBeTruthy()
    expect(container.querySelector('img')?.getAttribute('src')).toBe(card.imageUrl)
    expect(container.textContent).toContain('692094')
    expect(container.textContent).not.toMatch(/实付|交易|快递|风险/)
  })

  it('T2 picker sends sku or orderId only', async () => {
    vi.spyOn(customerApi, 'productOptions').mockResolvedValue([
      { source: 'order', sku: 'XC33002', name: '测试轻透粉底液', orderId: '6920947277927059788' }, card])
    const onPick = vi.fn()
    render(<ProductPicker conversationId="c1" onPick={onPick} />)
    fireEvent.click(screen.getByRole('button', { name: /商品/ }))
    fireEvent.click(await screen.findByText('测试轻透粉底液'))
    expect(onPick).toHaveBeenLastCalledWith({ orderId: '6920947277927059788' })
    fireEvent.click(screen.getByRole('button', { name: /商品/ }))
    fireEvent.click(await screen.findByText(card.name))
    expect(onPick).toHaveBeenLastCalledWith({ sku: card.sku })
  })

  it('T3 T4 desk header card facts and click', async () => {
    vi.spyOn(supportApi, 'productCard').mockResolvedValue({
      source: 'order', sku: 'XC33002', name: '测试轻透粉底液', orderId: '6920947277927059788',
      paidAmountMinor: 25900, currency: 'CNY', status: '交易成功', carrier: '圆通快递', city: '苏州市' })
    const onOpen = vi.fn()
    render(<DeskProductCard conversationId="c1" onOpenOrder={onOpen} />)
    expect(await screen.findByText('测试轻透粉底液')).toBeTruthy()
    for (const text of ['¥259.00', '6920947277927059788', '交易成功', '圆通快递 苏州市']) expect(screen.getByText(text)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /测试轻透粉底液/ }))
    expect(onOpen).toHaveBeenCalledWith('6920947277927059788')
  })

  it('T3 renders nothing without a source', async () => {
    const spy = vi.spyOn(supportApi, 'productCard').mockResolvedValue(null)
    const { container } = render(<DeskProductCard conversationId="c2" onOpenOrder={() => {}} />)
    await waitFor(() => expect(spy).toHaveBeenCalledWith('c2'))
    expect(container.textContent).toBe('')
  })
})
