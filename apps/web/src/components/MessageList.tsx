/**
 * 消息列表。
 *
 * 使用 Ant Design X 的 `Bubble` 复用成熟聊天气泡组件，不重写聊天基础组件。
 * 方向由 `messageSide()` 依据 senderRole + viewRole 计算（前端规范第 5.2 节）。
 *
 * 形态对齐参考图：一条消息＝「头像 + 角色名 + 时间」一行，下面是气泡。
 * 名字与时间在同一行（名 13px、时间 12px 次要色），气泡 15px、
 * 收到侧浅灰、发出侧薄荷（规范第 7.1 节）。
 */
import { RobotOutlined, UserOutlined } from '@ant-design/icons'
import { Bubble } from '@ant-design/x'
import { Avatar, Tag, Tooltip, Typography } from 'antd'
import { memo } from 'react'

import type { MessageView } from '../api/client'
import {
  messageSide,
  senderLabel,
  type SenderRole,
  type ViewRole,
} from '../features/conversation/messageDirection'

const { Text } = Typography

interface MessageListProps {
  messages: MessageView[]
  viewRole: ViewRole
  /** 发送失败的本地消息（不落库，仅提示）。 */
  failedKeys?: Record<string, string>
}

/** 头像：客户用人形图标，服务方用机器人图标，靠底色区分身份。 */
function roleAvatar(senderRole: SenderRole) {
  const isService = senderRole === 'assistant' || senderRole === 'operator'
  return (
    <Avatar
      size={38}
      style={{
        background: isService ? 'var(--anker-mint-surface)' : '#eef1f0',
        color: isService ? 'var(--anker-teal)' : 'var(--anker-muted)',
      }}
      icon={isService ? <RobotOutlined /> : <UserOutlined />}
      aria-hidden="true"
    />
  )
}

/**
 * 气泡里的附件缩略图。
 *
 * 客户上传的图片必须看得见——「传了图但没人看到」与没传没有区别。
 * 消息里只保存附件元数据（含取图地址），图片字节由后端按需返回，
 * 避免把 base64 塞进每条消息、把会话响应撑大几十倍。
 * 多模态未配置时图片仍然照常显示：看不了图的是模型，不是人。
 */
function AttachmentThumb({ attachment }: { attachment: Record<string, unknown> }) {
  const url = typeof attachment.url === 'string' ? attachment.url : null
  if (!url) {
    return null
  }
  const width = typeof attachment.width === 'number' ? attachment.width : 0
  const height = typeof attachment.height === 'number' ? attachment.height : 0
  const ratio = width > 0 && height > 0 ? width / height : 1
  return (
    <a href={url} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
      <img
        src={url}
        alt="图片附件"
        style={{
          display: 'block',
          maxWidth: 240,
          maxHeight: 200,
          width: ratio >= 1 ? 240 : undefined,
          borderRadius: 8,
          marginBottom: 6,
          objectFit: 'cover',
        }}
      />
    </a>
  )
}

export const MessageList = memo(function MessageList({
  messages,
  viewRole,
  failedKeys = {},
}: MessageListProps) {
  /**
   * `role="log"` 的容器**始终渲染**，空态也包含在里面。
   *
   * 原因：`aria-live` 区域必须在内容变化**之前**就存在于无障碍树里，屏幕阅读器
   * 才会播报新消息；若空会话时把整个 `role="log"` 卸载，第一条消息到达时区域是
   * 新建的，播报常常丢失。同时稳定的区域也让「消息列表」这个可访问名在任何
   * 会话状态下都可定位（此前空会话下该区域不存在，按名定位会超时）。
   */
  return (
    <div aria-label="消息列表" role="log" aria-live="polite">
      {messages.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center' }}>
          <Text type="secondary">开始新对话</Text>
        </div>
      ) : (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 20,
            padding: '18px 18px 10px',
          }}
        >
          {messages.map((message) => {
            const senderRole = message.senderRole as SenderRole
            const side = messageSide(senderRole, viewRole)
            const failure = failedKeys[message.messageId]

            return (
              <div key={message.messageId} style={{ display: 'flex', flexDirection: 'column' }}>
                <Bubble
                  placement={side === 'end' ? 'end' : 'start'}
                  variant={side === 'center' ? 'outlined' : 'filled'}
                  avatar={side === 'center' ? undefined : roleAvatar(senderRole)}
                  header={
                    side === 'center' ? undefined : (
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'baseline',
                          gap: 6,
                          paddingBottom: 4,
                        }}
                      >
                        <span style={{ fontSize: 13, color: 'var(--anker-graphite-soft)' }}>
                          {senderLabel(senderRole)}
                        </span>
                        <span style={{ fontSize: 12, color: 'var(--anker-muted)' }}>
                          {formatTime(message.createdAt)}
                        </span>
                      </span>
                    )
                  }
                  styles={{
                    /* 按「自己 / 对方」上色，而不是按身份：
                       客户视角下客户的消息是自己的（深色），客服视角下客服/Agent 的
                       消息是自己的——固定按身份上色会让客户界面看起来和服务方一样。 */
                    content: {
                      background:
                        side === 'center'
                          ? 'var(--anker-bubble-in)'
                          : side === 'end'
                            ? 'var(--anker-bubble-out)'
                            : 'var(--anker-bubble-in)',
                      borderRadius: 10,
                      padding: '10px 14px',
                      maxWidth: 560,
                      fontSize: 15,
                      lineHeight: 1.65,
                      color: 'var(--anker-graphite)',
                    },
                    avatar: { alignSelf: 'flex-start' },
                  }}
                  content={
                    <span className="anker-wrap" style={{ whiteSpace: 'pre-wrap' }}>
                      {/* 附件在气泡内展示：客户上传的故障照片必须看得见，
                          否则「传了图但没人看到」与没传没有区别。 */}
                      {message.attachments?.length
                        ? message.attachments.map((item, index) => (
                            <AttachmentThumb
                              key={String(item.attachmentId ?? index)}
                              attachment={item}
                            />
                          ))
                        : null}
                      {message.body || !message.attachments?.length ? message.body : null}
                    </span>
                  }
                />
                {failure ? (
                  <div style={{ marginTop: 6, textAlign: side === 'end' ? 'right' : 'left' }}>
                    <Tooltip title={failure}>
                      <Tag color="error">发送失败，可重试</Tag>
                    </Tooltip>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
})

function formatTime(iso: string): string {
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) {
    return ''
  }
  return parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
