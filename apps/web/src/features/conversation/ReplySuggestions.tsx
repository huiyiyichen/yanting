/**
 * AI 话术候选（客服侧）。
 *
 * 位置：中间聊天区底部、输入框上方，与已发送消息视觉隔离
 * （前端规范第 4 节：不把候选伪装成已发送气泡）。
 *
 * 列表主体复用 Ant Design X 的 `Prompts`（`vertical`）：参考图里三版候选
 * 是**同时铺开**的列表，而不是切换查看的单条；这样客服能一眼比对措辞差异。
 * 每行右侧的「采用」是**视觉落点**而不是嵌套按钮——`Prompts` 的条目本身就是
 * 可点击的按钮，在它内部再放一个 button 会造成嵌套交互控件；
 * 点击整行即采用，与「采用」胶囊的含义一致。
 *
 * 操作语义（第 6.1 节）：
 * - 采用：写入客服草稿，**不发送、不审批、不接管**
 * - 编辑：写入草稿并聚焦输入框
 * - 换一版：重新生成
 * - 忽略：收起候选，保留恢复生成入口
 * - 过期：新客户消息到达后必须提示重新核对，不得静默发送
 */
import { BulbOutlined, CloseOutlined, EditOutlined, ReloadOutlined } from '@ant-design/icons'
import { Prompts } from '@ant-design/x'
import { Alert, Button, Space, Spin, Tag, Tooltip, Typography } from 'antd'
import { useState } from 'react'

import type { NormalizedSuggestionSet, SuggestionView } from '../../api/client'

const { Text } = Typography

interface ReplySuggestionsProps {
  suggestions: NormalizedSuggestionSet | null
  loading: boolean
  error: string | null
  onGenerate: () => void
  /** 采用/编辑：只写草稿，不发送 */
  onAdopt: (suggestion: SuggestionView, focusEditor: boolean) => void
  onIgnore: (suggestion: SuggestionView) => void
  onDismiss: () => void
  /** 已有非空草稿时，替换前需确认 */
  hasDraft: boolean
}

export function ReplySuggestions({
  suggestions,
  loading,
  error,
  onGenerate,
  onAdopt,
  onIgnore,
  onDismiss,
  hasDraft,
}: ReplySuggestionsProps) {
  const [activeVariant, setActiveVariant] = useState('recommended')

  /* 未生成候选：只留一个入口 + 一句口径说明，不占视觉。 */
  if (!suggestions && !loading && !error) {
    return (
      <div style={{ padding: '2px 0 8px', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Button size="small" type="primary" ghost icon={<BulbOutlined />} onClick={onGenerate}>
          AI 生成回复候选
        </Button>
        <Text type="secondary" style={{ fontSize: 12 }}>
          候选来自真实模型；采用只填入草稿，不会发送
        </Text>
      </div>
    )
  }

  if (loading) {
    return (
      <div style={{ padding: '6px 0 10px' }}>
        <Space size={8}>
          <Spin size="small" />
          <Text type="secondary" style={{ fontSize: 13 }}>
            正在按当前上下文生成候选…
          </Text>
        </Space>
      </div>
    )
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        style={{ marginBottom: 8 }}
        title="候选生成失败"
        description={
          <Space orientation="vertical" size={4}>
            <span className="anker-wrap">{error}</span>
            <Text type="secondary" style={{ fontSize: 12 }}>
              仍可手动输入回复；候选失败不影响发送。
            </Text>
          </Space>
        }
        action={
          <Button size="small" icon={<ReloadOutlined />} onClick={onGenerate}>
            换一版
          </Button>
        }
      />
    )
  }

  if (!suggestions) {
    return null
  }

  const active =
    suggestions.items.find((item) => item.variant === activeVariant) ?? suggestions.items[0]
  const previewing = suggestions.items.map((item) => item.body).join('\n\n')

  return (
    <div className="anker-suggest" aria-label="AI 话术候选">
      <div className="anker-suggest-head">
        <span className="anker-suggest-title">
          <BulbOutlined aria-hidden="true" />
          AI 回复建议
        </span>
        <Text type="secondary" style={{ fontSize: 12 }}>
          三版同事实、同策略，仅措辞不同；采用只写草稿
        </Text>
        {suggestions.isMock ? <Tag color="purple">模拟</Tag> : null}
        {hasDraft ? (
          <Text type="secondary" style={{ fontSize: 11 }}>
            已有草稿，采用前会先确认替换
          </Text>
        ) : null}
      </div>

      {suggestions.expires ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 8 }}
          title="候选已过期"
          description="客户有新消息到达，请重新核对后再采用，不能直接发送旧候选。"
        />
      ) : null}

      {/* 三版候选同时铺开（`vertical`）；点整行即把该版写入草稿。
          过期的候选不允许采用，点击也走同一判定，不做「看似能点其实无效」。
          限高与内部滚动由 `.anker-suggest-list` 负责（窄屏更矮），
          否则三版完整措辞会把输入区顶出视口——实测过 composer 被撑到 1001px。 */}
      <div className="anker-scroll anker-suggest-list" style={{ marginTop: 6 }}>
        <Prompts
          vertical
          style={{ background: 'transparent' }}
          items={suggestions.items.map((item) => ({
            key: item.variant,
            label: (
              <span
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 10,
                  width: '100%',
                  minWidth: 0,
                }}
              >
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span
                    className="anker-wrap"
                    style={{
                      display: 'block',
                      fontSize: 15,
                      lineHeight: 1.65,
                      whiteSpace: 'pre-wrap',
                      color: 'var(--anker-graphite)',
                    }}
                  >
                    {item.body}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--anker-muted)' }}>
                    {item.variantLabel}
                  </span>
                </span>
                <span className="anker-adopt-pill" aria-hidden="true">
                  采用
                </span>
              </span>
            ),
          }))}
          onItemClick={(info) => {
            const picked = suggestions.items.find((item) => item.variant === info.data.key)
            if (!picked) {
              return
            }
            setActiveVariant(picked.variant)
            if (!suggestions.expires) {
              onAdopt(picked, false)
            }
          }}
        />
      </div>

      {/* 底部动作条：编辑 / 换一版 / 忽略（规范第 6.1 节的三个独立动作）。
          「采用」已在每行内，这里不重复放主按钮，避免两处都能采用造成的歧义。 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          marginTop: 6,
          paddingTop: 6,
          borderTop: '1px solid var(--anker-hairline)',
          flexWrap: 'wrap',
        }}
      >
        <Button
          size="small"
          icon={<EditOutlined />}
          disabled={suggestions.expires || !active}
          onClick={() => active && onAdopt(active, true)}
        >
          编辑
        </Button>
        <Button size="small" icon={<ReloadOutlined />} onClick={onGenerate}>
          换一版
        </Button>
        <Tooltip title="收起候选，保留恢复生成入口">
          <Button
            size="small"
            icon={<CloseOutlined />}
            aria-label="忽略候选"
            onClick={() => {
              if (active) {
                onIgnore(active)
              }
              onDismiss()
            }}
          >
            忽略
          </Button>
        </Tooltip>
        <Text
          type="secondary"
          style={{ fontSize: 11, marginInlineStart: 'auto', minWidth: 0 }}
          className="anker-wrap"
        >
          采用不等于发送，也不等于批准退款/换货
        </Text>
        {/* 屏幕阅读器可以一次读完整候选；视觉上仍是逐行阅读。 */}
        <span className="anker-visually-hidden">候选全文：{previewing}</span>
      </div>
    </div>
  )
}
