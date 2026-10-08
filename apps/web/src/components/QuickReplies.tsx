/**
 * 新会话快捷选项（客户侧）。
 *
 * 用户要求：新会话开始时服务方先给一段固定开场白，下面给几个**能点的**按钮，
 * 点了之后会自动追问或给出相关信息；用户不点、直接打字也要能正常走流程。
 *
 * 实现边界：按钮点击后就是把 `prompt` 当作一条普通客户消息发出去
 * （见 `CustomerView.handleQuickReply`），没有任何"按钮专用"的分支。
 * 文案与问题清单来自后端 `GET /api/customer/onboarding`，前端不维护第二份。
 */

interface QuickRepliesProps {
  items: { label: string; prompt: string }[]
  disabled?: boolean
  onPick: (prompt: string) => void
}

export function QuickReplies({ items, disabled = false, onPick }: QuickRepliesProps) {
  if (items.length === 0) {
    return null
  }
  return (
    <div style={{ padding: '0 18px 16px' }} aria-label="常见问题快捷入口">
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {items.map((item) => (
          <button
            key={item.label}
            type="button"
            disabled={disabled}
            onClick={() => onPick(item.prompt)}
            style={{
              padding: '6px 12px',
              borderRadius: 16,
              border: '1px solid #d6e4ff',
              background: '#f0f5ff',
              color: '#1677ff',
              fontSize: 13,
              font: 'inherit',
              cursor: disabled ? 'not-allowed' : 'pointer',
            }}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  )
}
