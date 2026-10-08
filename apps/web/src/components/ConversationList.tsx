/**
 * 会话列表。
 *
 * 客户侧显示自己的售后会话；客服侧显示待处理/处理中队列。
 * 切换会话不发送草稿、不中断其他会话已发出的请求。
 *
 * **性能约束（不要去掉 `memo`）**：列表会一次性渲染全部会话，而输入框每敲一个字
 * 都会让页面重渲染。没有 `memo` 时，一次按键要把整张列表重算一遍——实测 792 条会话下
 * 每次按键 786ms（见 `e2e/_typing-latency.mjs`），用户直接感觉为「输入卡顿」。
 * 配合调用方用 `useCallback` 固定回调，`memo` 才能命中。
 *
 * 列表主体复用 Ant Design X 的 `Conversations`（工程规范：复用成熟聊天构件，
 * 不重写聊天基础组件）。三点必须注意：
 *
 * 1. `Conversations` 渲染出的 `<li>` **不可聚焦、没有 button 语义**，
 *    键盘用户无法操作。因此每项的 `label` 内部放一个真正的 `<button>`，
 *    保证键盘可达与屏幕阅读器可读（工程规范第 5 节与前端规范第 7 节）。
 *    这也保持了既有 e2e 用 `getByRole('button', { name })` 定位会话的写法。
 * 2. 列表本身显式给 `role="list"` 与 `aria-label`，让「会话队列 / 我的售后会话」
 *    这个区域语义不依赖外层 `<aside>` 的推断。
 * 3. 行样式（头像 / 名称 / 时间 / 摘要 / 选中态）按前端规范第 7.1 节的对齐参考图
 *    规格来：选中整行薄荷底、名称 15px 加粗、时间与摘要 12—13px 次要色。
 *
 * 搜索框只过滤**已加载**的会话（标题与摘要），不做服务端检索：
 * 本期会话列表本来就是一次性拉全量，加一个假的服务端搜索入口反而误导。
 */
import {
  DeleteOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Conversations } from '@ant-design/x'
import { Avatar, Button, Empty, Input, Popconfirm, Skeleton, Tag, Tooltip, Typography } from 'antd'
import { memo, useMemo, useState } from 'react'

const { Text } = Typography

/** 侧栏固定宽度：右侧遮罩与浮层定位都依赖它，避免两处各写一份魔法数字。 */
const PANEL_WIDTH = 248

export interface ConversationListItem {
  conversationId: string
  title: string
  preview?: string
  /** 客服队列才有的附加信息 */
  badge?: string
  badgeColor?: string
  meta?: string
}

interface ConversationListProps {
  items: ConversationListItem[]
  activeId: string | null
  loading: boolean
  error: string | null
  onSelect: (conversationId: string) => void
  onCreate?: () => void
  onRefresh: () => void
  /** 删除会话（提供后每行显示删除入口；不提供则不显示，避免假按钮） */
  onDelete?: (conversationId: string) => void
  /** 无数据时的空状态文案 */
  emptyText?: string
  ariaLabel: string
  createLabel?: string
  creating?: boolean
  /** 是否显示；false 时仍挂载但隐藏，保证结构与测试选择器稳定 */
  visible?: boolean
  /** 提供后显示收起按钮 */
  onCollapse?: () => void
  /**
   * 窄屏覆盖模式。
   *
   * 窄屏下 248px 的固定侧栏会把聊天区压到几十像素（中文逐字换行、
   * 输入框不可用）。覆盖模式下改为浮层：不占据行内宽度，并在其下加
   * 可点击遮罩，避免「队列盖住聊天却仍能点到后面」的误操作。
   */
  overlay?: boolean
  onDismiss?: () => void
  /** 窄屏覆盖层的左上角内边距（让开左侧图标栏） */
  overlayInset?: number
  /** 窄屏覆盖层的顶部起点（让开运行状态横幅） */
  overlayTop?: number
}

/** 单项的「双行」结构：首行身份+时间/状态，次行摘要，两行各自截断互不挤压。 */
function ConversationRow({
  item,
  active,
  onDelete,
}: {
  item: ConversationListItem
  active: boolean
  onDelete?: (conversationId: string) => void
}) {
  /* 结构说明（不要改回去）：
     行本身必须是一个真正的 `<button>`（键盘可达，见缺陷第 42 项），
     而删除按钮也是 button —— **两者不能嵌套**，否则是无效 HTML，点击删除还会连带选中会话。
     因此外层是定位容器，行按钮与删除按钮是兄弟节点，删除按钮绝对定位在右上角。 */
  return (
    <div style={{ position: 'relative' }}>
      <button
        type="button"
        className="anker-conv-row"
        aria-current={active ? 'true' : undefined}
        style={{
          display: 'flex',
          gap: 10,
          alignItems: 'flex-start',
          width: '100%',
          minWidth: 0,
          paddingRight: onDelete ? 30 : undefined,
          border: 'none',
          background: 'transparent',
          textAlign: 'left',
          font: 'inherit',
          cursor: 'pointer',
        }}
      >
        <Avatar
          size={38}
          style={{
            background: active ? 'var(--anker-mint-surface)' : '#f1f4f3',
            color: active ? 'var(--anker-teal-dark)' : 'var(--anker-muted)',
            flexShrink: 0,
          }}
          icon={<UserOutlined />}
        />
        <span style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
            <span
              className="anker-conv-name anker-wrap"
              style={{
                flex: 1,
                minWidth: 0,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {item.title || '新会话'}
            </span>
            {item.badge ? (
              <Tag
                color={item.badgeColor ?? 'default'}
                style={{ marginInlineEnd: 0, flexShrink: 0, fontSize: 11 }}
              >
                {item.badge}
              </Tag>
            ) : null}
            {item.meta ? <span className="anker-conv-time">{item.meta}</span> : null}
          </span>
          <span
            className="anker-conv-preview anker-wrap"
            style={{
              display: '-webkit-box',
              WebkitLineClamp: 2,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {item.preview || '暂无消息'}
          </span>
        </span>
      </button>

      {/* 删除入口：级联删除且不可恢复，用 Popconfirm 二次确认；审计保留 */}
      {onDelete ? (
        <Popconfirm
          title="删除这个会话？"
          description="消息、附件、案件与申请会一并删除且不可恢复；审计记录保留。"
          okText="删除"
          okButtonProps={{ danger: true }}
          cancelText="取消"
          onConfirm={() => onDelete(item.conversationId)}
        >
          <Button
            type="text"
            size="small"
            danger
            icon={<DeleteOutlined />}
            aria-label={`删除会话 ${item.title || '新会话'}`}
            style={{ position: 'absolute', top: 6, right: 4 }}
          />
        </Popconfirm>
      ) : null}
    </div>
  )
}

export const ConversationList = memo(function ConversationList({
  items,
  activeId,
  loading,
  error,
  onSelect,
  onCreate,
  onRefresh,
  onDelete,
  emptyText = '暂无会话',
  ariaLabel,
  createLabel = '新建会话',
  creating = false,
  visible = true,
  onCollapse,
  overlay = false,
  onDismiss,
  overlayInset = 80,
  overlayTop = 0,
}: ConversationListProps) {
  const [keyword, setKeyword] = useState('')

  /* 本地过滤：标题或摘要包含关键词。空关键词返回原列表。 */
  const filtered = useMemo(() => {
    const needle = keyword.trim().toLowerCase()
    if (!needle) {
      return items
    }
    return items.filter((item) =>
      `${item.title} ${item.preview ?? ''}`.toLowerCase().includes(needle),
    )
  }, [items, keyword])

  const showList = filtered.length > 0 && !error
  const searching = keyword.trim().length > 0

  return (
    <>
      {overlay && visible ? (
        /* 浮层遮罩：只覆盖浮层之外的可视区域，点击即收起。
           `aside` 在 DOM 中位于聊天区之前且为 fixed 定位，本身就在遮罩之上，
           因此不需要额外的透明点击层（那会盖住聊天头部控件）。 */
        <div
          role="presentation"
          aria-hidden="true"
          onClick={onDismiss}
          style={{
            position: 'fixed',
            top: overlayTop,
            bottom: 0,
            left: overlayInset + PANEL_WIDTH,
            right: 0,
            zIndex: 29,
            background: 'rgba(31, 35, 40, 0.24)',
          }}
        />
      ) : null}
      <aside
        className="anker-panel"
        style={{
          width: PANEL_WIDTH,
          flexShrink: 0,
          display: visible ? 'flex' : 'none',
          ...(overlay
            ? {
                position: 'fixed' as const,
                top: overlayTop,
                bottom: 0,
                left: overlayInset,
                zIndex: 30,
                maxWidth: `calc(100vw - ${overlayInset + 24}px)`,
                boxShadow: '2px 0 16px rgba(31, 42, 42, 0.16)',
              }
            : null),
        }}
        aria-label={ariaLabel}
        aria-hidden={!visible}
        data-overlay={overlay ? 'true' : undefined}
      >
        <div className="anker-list-head anker-hairline-bottom">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <h2 className="anker-list-title" style={{ flex: 1, minWidth: 0 }}>
              {ariaLabel}
            </h2>
            {onCreate ? (
              <Tooltip title={createLabel}>
                <Button
                  type="text"
                  size="small"
                  icon={<PlusOutlined />}
                  aria-label={createLabel}
                  loading={creating}
                  onClick={onCreate}
                />
              </Tooltip>
            ) : null}
            <Tooltip title="刷新列表">
              <Button
                type="text"
                size="small"
                icon={<ReloadOutlined />}
                aria-label="刷新列表"
                onClick={onRefresh}
                loading={loading}
              />
            </Tooltip>
            {onCollapse ? (
              <Tooltip title="收起会话队列">
                <Button
                  type="text"
                  size="small"
                  icon={<MenuFoldOutlined />}
                  aria-label="收起会话队列"
                  onClick={onCollapse}
                />
              </Tooltip>
            ) : null}
          </div>

          <Input
            allowClear
            size="middle"
            variant="borderless"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            prefix={<SearchOutlined style={{ color: 'var(--anker-muted)' }} />}
            placeholder="搜索会话、型号、问题…"
            aria-label="搜索会话"
            style={{ padding: 0, marginTop: 2 }}
          />
        </div>

        <div className="anker-scroll" style={{ flex: 1 }}>
          {loading && items.length === 0 ? (
            <div style={{ padding: 16 }}>
              <Skeleton active paragraph={{ rows: 3 }} title={false} />
            </div>
          ) : error ? (
            <div style={{ padding: 16 }}>
              <Text type="danger" className="anker-wrap" style={{ fontSize: 13 }}>
                {error}
              </Text>
              <Button size="small" onClick={onRefresh} style={{ marginTop: 8 }}>
                重试
              </Button>
            </div>
          ) : items.length === 0 ? (
            <div style={{ padding: 16 }}>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={<span style={{ color: 'var(--anker-muted)' }}>{emptyText}</span>}
              />
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ padding: 16 }}>
              <Text type="secondary" style={{ fontSize: 13 }}>
                没有匹配「{keyword.trim()}」的会话
              </Text>
            </div>
          ) : null}

          {showList ? (
            <Conversations
              activeKey={activeId ?? undefined}
              onActiveChange={(key) => onSelect(String(key))}
              role="list"
              aria-label={ariaLabel}
              style={{ padding: '6px 8px 10px', background: 'transparent' }}
              items={filtered.map((item) => ({
                key: item.conversationId,
                /* 头像与两行文本都在 `label` 内自己排版：`Conversations`
                   的 `icon` 槽位只有固定宽度，放不下「头像 + 双行 + 状态标签」。 */
                label: (
                  <ConversationRow
                    item={item}
                    active={item.conversationId === activeId}
                    onDelete={onDelete}
                  />
                ),
              }))}
            />
          ) : null}

          {searching && filtered.length > 0 ? (
            <div style={{ padding: '0 16px 12px' }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                已在 {items.length} 个会话中筛出 {filtered.length} 个
              </Text>
            </div>
          ) : null}
        </div>
      </aside>
    </>
  )
})

/** 会话队列收起后的展开入口，供窄屏使用。 */
export function ExpandQueueButton({ onClick }: { onClick: () => void }) {
  return (
    <Tooltip title="展开会话队列">
      <Button
        size="small"
        type="text"
        icon={<MenuUnfoldOutlined />}
        aria-label="展开会话队列"
        onClick={onClick}
      />
    </Tooltip>
  )
}
