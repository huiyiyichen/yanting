import { ShoppingOutlined } from '@ant-design/icons'
import { useEffect, useState } from 'react'
import { supportApi, type DeskProductCardView } from '../../api/client'

const money = (minor?: number | null) => (minor == null ? null : `¥${(minor / 100).toFixed(2)}`)

/** 聊天区顶部商品卡：最新商品卡消息 → 本会话关联订单；无来源不渲染。 */
export function DeskProductCard({ conversationId, refreshKey, onOpenOrder }: {
  conversationId: string
  refreshKey?: unknown
  onOpenOrder: (orderId: string | null) => void
}) {
  const [card, setCard] = useState<DeskProductCardView | null>(null)
  useEffect(() => {
    let alive = true
    setCard(null)
    supportApi.productCard(conversationId).then((next) => { if (alive) setCard(next) }).catch(() => undefined)
    return () => { alive = false }
  }, [conversationId, refreshKey])
  if (!card) return null
  const logistics = [card.carrier, card.city].filter(Boolean).join(' · ')
  return (
    <button type="button" className="yt-desk-product" onClick={() => onOpenOrder(card.orderId ?? null)} aria-label={card.name}>
      {card.imageUrl ? <img src={card.imageUrl} alt="" /> : <span className="yt-product-card-ph"><ShoppingOutlined /></span>}
      <span className="yt-desk-product-main">
        <strong>{card.name}</strong>
        <span className="yt-desk-product-facts">
          {money(card.paidAmountMinor) && <span>{money(card.paidAmountMinor)}</span>}
          {card.orderId && <span>{card.orderId}</span>}
          {card.status && <span>{card.status}</span>}
          {logistics && <span>{logistics}</span>}
          {!card.orderId && card.sku && <span>{card.sku}</span>}
        </span>
      </span>
    </button>
  )
}
