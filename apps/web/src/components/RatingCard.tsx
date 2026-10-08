/**
 * 满意度评价卡（客户侧）。
 *
 * 用户反馈：原来的评价是输入框上方一条 8px 高的小字 + 小星星，"位置不对、太小"，
 * 期望像电商客服那样**在会话结束时**出现一张明显的卡片。
 *
 * 设计取舍：
 * - 五个表情按钮各自带文字标签（很不满→很满意），不用纯星星：表情 + 文字在窄屏也读得懂，
 *   而且点哪一档就是几分，不需要用户去数第几颗星；
 * - 点一下即提交（与参考图一致），提交中禁用避免连点重复提交；
 * - 「跳过」是真实存在的动作（状态机里有 `skipped`），不是装饰；
 * - 没有加"您的问题解决了吗"那一行：本期数据模型只有 1—5 分与跳过，
 *   加一个不落库的选择就是假控件。
 */
import { Button, Space, Typography } from 'antd'

const { Text } = Typography

/** 五档：分值 → 表情 + 文案。文案与分值一一对应，不做"看起来更丰富"的扩展。 */
const SCALE: { value: number; emoji: string; label: string }[] = [
  { value: 1, emoji: '😞', label: '很不满' },
  { value: 2, emoji: '🙁', label: '不满' },
  { value: 3, emoji: '😐', label: '一般' },
  { value: 4, emoji: '🙂', label: '满意' },
  { value: 5, emoji: '😍', label: '很满意' },
]

interface RatingCardProps {
  busy?: boolean
  onSubmit: (value: number) => void
  onSkip: () => void
}

export function RatingCard({ busy = false, onSubmit, onSkip }: RatingCardProps) {
  return (
    <section
      aria-label="满意度评价"
      style={{
        margin: '4px 18px 16px',
        padding: '16px 18px',
        border: '1px solid var(--anker-hairline, #f0f0f0)',
        borderRadius: 12,
        background: '#fff',
        boxShadow: '0 2px 10px rgba(0, 0, 0, 0.04)',
      }}
    >
      <Text strong style={{ fontSize: 15 }}>
        本次服务已结束，请为这次体验评分
      </Text>
      <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {SCALE.map((item) => (
          <button
            key={item.value}
            type="button"
            disabled={busy}
            aria-label={`评分 ${item.value} 分：${item.label}`}
            onClick={() => onSubmit(item.value)}
            style={{
              flex: '1 1 88px',
              minWidth: 88,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 4,
              padding: '10px 6px',
              background: '#fafafa',
              border: '1px solid #f0f0f0',
              borderRadius: 10,
              cursor: busy ? 'not-allowed' : 'pointer',
              font: 'inherit',
            }}
          >
            <span style={{ fontSize: 26, lineHeight: 1 }} aria-hidden="true">
              {item.emoji}
            </span>
            <span style={{ fontSize: 12, color: 'var(--anker-muted, #8c8c8c)' }}>
              {item.label}
            </span>
          </button>
        ))}
      </div>
      <Space style={{ marginTop: 10 }} size={8}>
        <Button size="small" disabled={busy} onClick={onSkip}>
          跳过
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          评分只用于改进服务；跳过不会影响本次处理结果
        </Text>
      </Space>
    </section>
  )
}
