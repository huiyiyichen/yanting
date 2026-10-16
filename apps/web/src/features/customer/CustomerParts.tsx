/**
 * 客户页分块（自 CustomerView 拆出，P2-2）：会话头、服务评价、输入区。
 * 只接收客户自己可见的数据——不得传入风险、情绪、知识依据等内部字段。
 */
import { CustomerServiceOutlined, RobotOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { Sender } from '@ant-design/x'
import { Alert, Avatar, Button, Spin, Typography } from 'antd'
import type { ApiError, ConversationSummary, ProductRef } from '../../api/client'
import { ChatImageButton, ChatImagePreview, type useChatImage } from '../../components/ChatImageUpload'
import { ProductPicker } from '../../components/ProductCard'
import { RatingCard } from '../../components/RatingCard'
import { SenderSendButton, makeSenderInput } from '../../components/SenderParts'

const { Text } = Typography
const CUSTOMER_COMPOSER_INPUT = makeSenderInput('客户消息输入框')

export function CustomerChatHead({ conversation, aiReplying, transferring, canHandoff, onHandoff, showListButton, onOpenList }: {
  conversation?: ConversationSummary | null
  aiReplying: boolean
  transferring: boolean
  canHandoff: boolean
  onHandoff: () => void
  showListButton: boolean
  onOpenList: () => void
}) {
  return <>
  {/* 对话头部：这里只放真实存在的东西——会话标题、状态与两个真按钮。
      窄屏必须有进入会话列表的入口，否则无法切换或新建会话。 */}
  <div className="yt-base-chat-head yt-hairline-bottom">
    <Avatar
      size={40}
      style={{ background: 'var(--yt-mint-surface)', color: 'var(--yt-teal)' }}
      icon={conversation?.serviceMode === 'operator_assisted' ? <CustomerServiceOutlined /> : <RobotOutlined />}
      aria-hidden="true"
    />
    <div className="yt-chat-head-text">
      <span
        className="yt-chat-title yt-wrap"
        style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
      >
        {conversation?.title || '智能助手'}
      </span>
      {conversation && <span className="yt-base-chip">
        {conversation.serviceMode === 'operator_assisted' ? '人工接待' : aiReplying ? 'AI 回复中' : 'AI 接待'}
      </span>}
    </div>
    <div className="yt-base-chat-head-actions">
      <Button size="small" icon={<CustomerServiceOutlined />} aria-label="转人工"
        disabled={!canHandoff}
        loading={transferring} onClick={onHandoff}>转人工</Button>
      {showListButton ? (
        <Button
          size="small"
          icon={<UnorderedListOutlined />}
          onClick={onOpenList}
        >
          会话列表
        </Button>
      ) : null}
    </div>
  </div>
  </>
}

export type ServiceRatingState = { status: string; value: number | null } | null

export function ratingText(rating: ServiceRatingState): string | null {
  if (!rating || rating.status === 'not_requested') return null
  return rating.status === 'submitted' ? `本次服务已评价：${rating.value ?? '—'} 分，感谢反馈`
    : rating.status === 'skipped' ? '本次服务已结束（未评分）' : '待评价'
}

/** 服务结束时的评价卡；提交或跳过后只留一行结果。 */
export function ServiceRating({ open, busy, rating, onSubmit }: {
  open: boolean
  busy: boolean
  rating: ServiceRatingState
  onSubmit: (value: number | null) => void
}) {
  if (open) return <RatingCard busy={busy} onSubmit={onSubmit} onSkip={() => onSubmit(null)} />
  const text = ratingText(rating)
  return text ? <div style={{ padding: '0 18px 14px' }}><Text type="secondary" style={{ fontSize: 12 }}>{text}</Text></div> : null
}

export function CustomerComposer({ conversationId, draft, onDraft, onSubmit, onSendProduct, sending, aiReplying, narrow, imageUpload, sendError, onClearSendError }: {
  conversationId: string | null
  draft: string
  onDraft: (next: string) => void
  onSubmit: () => void
  onSendProduct: (product: ProductRef) => void
  sending: boolean
  aiReplying: boolean
  narrow: boolean
  imageUpload: ReturnType<typeof useChatImage>
  sendError: ApiError | null
  onClearSendError: () => void
}) {
  const uploadedImage = imageUpload.image?.attachment?.attachmentId
  const uploading = imageUpload.image?.uploading ?? false
  return <div className="yt-composer yt-hairline-top">
  {aiReplying && <div className="auto-reply-state" role="status"><Spin size="small" /><span>AI 回复中</span></div>}
  {sendError ? (
    <Alert
      type={sendError.isPermissionDenied ? 'warning' : 'error'}
      showIcon
      closable={{ onClose: onClearSendError }}
      style={{ marginBottom: 8 }}
      title={sendError.message}
      description={sendError.detail ?? undefined}
    />
  ) : null}
  {imageUpload.image?.error ? (
    <Alert
      type="error"
      showIcon
      closable={{ onClose: () => imageUpload.clear() }}
      style={{ marginBottom: 8 }}
      title="图片上传失败"
      description={<span className="yt-wrap">{imageUpload.image.error}</span>}
    />
  ) : null}
  <ChatImagePreview image={imageUpload.image} onRemove={() => imageUpload.clear()}
    disabled={sending || uploading} />
  <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6 }}>
    <ChatImageButton upload={imageUpload.upload} disabled={!conversationId || sending || uploading}
      uploading={uploading} />
    <ProductPicker conversationId={conversationId} disabled={sending || uploading}
      onPick={onSendProduct} />
    <div style={{ flex: 1, minWidth: 0 }}>
      <Sender
        value={draft}
        onChange={onDraft}
        onSubmit={onSubmit}
        onPasteFile={(files) => { if (files[0]) void imageUpload.upload(files[0]) }}
        loading={sending}
        disabled={!conversationId || sending}
        /* 窄屏输入盒被回形针与发送按钮占去两侧，长占位文案会折行 */
        placeholder={
          conversationId
            ? narrow
              ? '描述问题…'
              : '描述您遇到的问题…'
            : '请先新建会话'
        }
        autoSize={{ minRows: 1, maxRows: 5 }}
        submitType="enter"
        components={{ input: CUSTOMER_COMPOSER_INPUT }}
        suffix={(_, { components }) => (
          <SenderSendButton
            component={components.SendButton}
            disabled={(!draft.trim() && !uploadedImage) || !conversationId || sending || uploading}
            loading={sending}
          />
        )}
      />
    </div>
  </div>
</div>
}
