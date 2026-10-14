import { ShoppingOutlined } from '@ant-design/icons'
import { Button, Popover, Spin } from 'antd'
import { useState } from 'react'
import { customerApi, type ProductCardView, type ProductRef } from '../api/client'

/** 消息里的商品卡：只展示商品身份（图、名称、货号或订单号）。 */
export function ProductCardBubble({ card }: { card: ProductCardView }) {
  return (
    <span className="yt-product-card">
      {card.imageUrl ? <img src={card.imageUrl} alt="" /> : <span className="yt-product-card-ph"><ShoppingOutlined /></span>}
      <span className="yt-product-card-text">
        <strong>{card.name}</strong>
        <small>{card.orderId ? `订单号 ${card.orderId}` : card.sku}</small>
      </span>
    </span>
  )
}

/** 客户输入区“商品”按钮：从本会话订单或商品目录选择，只回传 SKU 或订单号。 */
export function ProductPicker({ conversationId, disabled, onPick }: {
  conversationId: string | null
  disabled?: boolean
  onPick: (ref: ProductRef) => void
}) {
  const [open, setOpen] = useState(false)
  const [options, setOptions] = useState<ProductCardView[] | null>(null)
  const toggle = (next: boolean) => {
    setOpen(next)
    if (next && conversationId) {
      setOptions(null)
      customerApi.productOptions(conversationId).then(setOptions).catch(() => setOptions([]))
    }
  }
  const content = options === null ? <Spin size="small" /> : (
    <div className="yt-product-picker">
      {options.map((item) => (
        <button type="button" key={`${item.source}-${item.orderId ?? item.sku}`} onClick={() => {
          setOpen(false)
          onPick(item.orderId ? { orderId: item.orderId } : { sku: item.sku })
        }}>
          <ProductCardBubble card={item} />
        </button>
      ))}
    </div>
  )
  return (
    <Popover open={open} onOpenChange={toggle} trigger="click" content={content} placement="topLeft">
      <Button type="text" icon={<ShoppingOutlined />} disabled={disabled || !conversationId} aria-label="商品">商品</Button>
    </Popover>
  )
}
