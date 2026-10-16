/**
 * 客户视角。
 *
 * 归属约束（前端规范第 3 节）：只包含会话列表、新建会话、普通消息、图片与输入框。
 * **不挂载** AI 判断、话术候选、内部依据面板与审批控件（AC-24）。
 *
 * 已发送消息一律以后端为准；本地只保留按会话隔离的未发送草稿。
 */
import { Alert, Button, Spin } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, customerApi, type ConversationSummary, type MessageView, type ProductRef } from '../api/client'
import { ConversationList } from '../components/ConversationList'
import { useChatImage } from '../components/ChatImageUpload'
import { MessageList } from '../components/MessageList'
import { QuickReplies } from '../components/QuickReplies'
import { CustomerChatHead, CustomerComposer, ServiceRating } from '../features/customer/CustomerParts'
import { useDraftStore } from '../features/conversation/draftStore'
import { newClientMessageKey } from '../features/conversation/messageDirection'
import { useIsNarrow } from '../hooks/useMediaQuery'
import { CUSTOMER_LAYOUT, OVERLAY_LAYOUT } from '../styles/layout'
import { visibleInterval } from '../hooks/visibleInterval'


/** 演示身份：地址参数 ?customer= 优先，其次启动时注入的 VITE_DEMO_CUSTOMER_ID。 */
function demoCustomerId(): string {
  const fromQuery = new URLSearchParams(window.location.search).get('customer')?.trim()
  const fromEnv = (import.meta.env.VITE_DEMO_CUSTOMER_ID as string | undefined)?.trim()
  return fromQuery || fromEnv || 'CUST-DEMO-01'
}

const CUSTOMER_ID = demoCustomerId()

/** 输入控件的可访问名：e2e 与屏幕阅读器共用同一个名字。 */

/**
 * 发送按钮的提交闭包通过 ref 传递。
 *
 * `Sender` 的 `suffix` 是渲染函数而不是组件，在其中直接闭包捕获 `draft`
 * 会拿到过期值；因此每次渲染把「当前有效的提交动作」写入 ref，
 * 按钮点击时读取，保证用的是最新草稿。
 */
export function CustomerView() {
  // 窄屏下 248px 固定会话列表会把聊天区压到不可用宽度，
  // 因此改为浮层（与客服队列一致），默认收起并给一个明确入口。
  const isNarrowList = useIsNarrow(CUSTOMER_LAYOUT.listCollapseBreakpoint)
  const [listOpenOverride, setListOpenOverride] = useState<boolean | null>(null)
  const showList = listOpenOverride ?? !isNarrowList
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageView[]>([])
  const [listError, setListError] = useState<string | null>(null)
  const [messageError, setMessageError] = useState<string | null>(null)
  const [sendError, setSendError] = useState<ApiError | null>(null)
  const [loadingList, setLoadingList] = useState(false)
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [sending, setSending] = useState(false)
  const [creating, setCreating] = useState(false)
  const [transferring, setTransferring] = useState(false)
  const [rating, setRating] = useState<{ status: string; value: number | null } | null>(null)
  const [ratingOpen, setRatingOpen] = useState(false)
  const [ratingBusy, setRatingBusy] = useState(false)
  const [onboarding, setOnboarding] = useState<{
    greeting: string
    quickReplies: { label: string; prompt: string }[]
  } | null>(null)
  const imageUpload = useChatImage(activeId, customerApi.uploadAttachment)
  const uploadedImage = imageUpload.image?.attachment?.attachmentId
  const uploading = imageUpload.image?.uploading ?? false

  const drafts = useDraftStore()
  const activeIdRef = useRef<string | null>(null)
  activeIdRef.current = activeId

  const draft = activeId ? drafts.get(activeId, 'customer') : ''
  /** 对话头部展示的会话（标题由服务端按首条客户消息生成）。 */
  const activeConversation = conversations.find((item) => item.conversationId === activeId) ?? null
  const aiReplying = activeConversation?.serviceMode === 'autonomous'
    && ['queued', 'running'].includes(activeConversation.autoReplyStatus ?? '')

  const handoff = async () => {
    const target = activeIdRef.current
    if (!target) return
    setTransferring(true)
    try {
      await customerApi.handoff(target)
      await Promise.all([loadConversations(), loadMessages(target)])
    } catch (error) { setSendError(error as ApiError) }
    finally { setTransferring(false) }
  }

  /** 发送按钮点击时调用：始终指向最新一次渲染的发送闭包。 */
  const submitRef = useRef<() => void>(() => undefined)
  submitRef.current = () => {
    if (activeId && (draft.trim() || uploadedImage) && !sending && !uploading) {
      void handleSend()
    }
  }

  const loadConversations = useCallback(async (): Promise<ConversationSummary[]> => {
    setLoadingList(true)
    try {
      const list = await customerApi.listConversations(CUSTOMER_ID)
      setConversations(list)
      setListError(null)
      return list
    } catch (error) {
      setListError((error as ApiError).message)
      return []
    } finally {
      setLoadingList(false)
    }
  }, [])

  const loadMessages = useCallback(async (conversationId: string) => {
    setLoadingMessages(true)
    try {
      const list = await customerApi.listMessages(conversationId)
      // 异步结果只回写原会话，避免切换会话后串线
      if (activeIdRef.current === conversationId) {
        setMessages(list)
        setMessageError(null)
      }
    } catch (error) {
      if (activeIdRef.current === conversationId) {
        setMessageError((error as ApiError).message)
      }
    } finally {
      setLoadingMessages(false)
    }
  }, [])

  const selectConversation = useCallback(
    (conversationId: string, options?: { userInitiated?: boolean }) => {
      activeIdRef.current = conversationId
      setActiveId(conversationId)
      setSendError(null)
      setRatingOpen(false)
      setRating(null)
      setMessages([])
      setMessageError(null)
      // 只有窄屏浮层才在用户选会话后收起；宽屏列表是常驻侧栏，
      // 收起它会让列表彻底消失且没有重新打开的入口（已实测到该缺陷）。
      if (options?.userInitiated && isNarrowList) {
        setListOpenOverride(false)
      }
      void loadMessages(conversationId)
      void customerApi.listConversations(CUSTOMER_ID).then((list) => {
        if (activeIdRef.current === conversationId) setConversations(list)
      }).catch(() => undefined)
      void customerApi
        .getRating(conversationId)
        .then((result) => {
          if (result && activeIdRef.current === conversationId) {
            setRating({ status: result.ratingStatus, value: result.userRating ?? null })
            setRatingOpen(result.ratingStatus === 'pending')
          }
        })
        .catch(() => undefined)
    },
    [isNarrowList, loadMessages],
  )

  useEffect(() => {
    void loadConversations().then((list) => {
      if (list.length > 0) {
        selectConversation(list[0].conversationId)
      }
    })
  }, [loadConversations, selectConversation])

  useEffect(() => {
    let disposed = false
    let pending = false
    const sync = async () => {
      if (pending || document.visibilityState === 'hidden') return
      pending = true
      try {
        const list = await customerApi.listConversations(CUSTOMER_ID)
        if (!disposed) setConversations(list)
        const origin = activeIdRef.current
        if (origin) {
          const [rows, currentRating] = await Promise.all([
            customerApi.listMessages(origin), customerApi.getRating(origin),
          ])
          if (!disposed && activeIdRef.current === origin) {
            setMessages(rows)
            setMessageError(null)
            if (currentRating) {
              setRating({ status: currentRating.ratingStatus, value: currentRating.userRating ?? null })
              if (currentRating.ratingStatus === 'pending') setRatingOpen(true)
            }
          }
        }
      } catch (err) {
        if (!disposed) setListError((err as Error).message)
      } finally { pending = false }
    }
    const stop = visibleInterval(() => void sync(), 1000)
    return () => { disposed = true; stop() }
  }, [])

  /** 开场白与快捷选项：文案来自后端，取不到就不显示快捷入口（不编一套本地文案）。 */
  useEffect(() => {
    void customerApi
      .onboarding()
      .then((result) =>
        setOnboarding({
          greeting: result.greeting,
          quickReplies: result.quickReplies ?? [],
        }),
      )
      .catch(() => setOnboarding(null))
  }, [])

  const handleCreate = useCallback(async () => {
    setCreating(true)
    try {
      const created = await customerApi.createConversation(CUSTOMER_ID)
      await loadConversations()
      selectConversation(created.conversationId)
    } catch (error) {
      setListError((error as ApiError).message)
    } finally {
      setCreating(false)
    }
  }, [loadConversations, selectConversation])

  const handleDelete = useCallback(
    async (conversationId: string) => {
      try {
        await customerApi.deleteConversation(conversationId)
        // 删的是当前会话时清空详情，避免继续显示已删除的数据
        if (activeIdRef.current === conversationId) {
          setActiveId(null)
          setMessages([])
          setRating(null)
          setRatingOpen(false)
        }
        await loadConversations()
      } catch (error) {
        setSendError(error as ApiError)
      }
    },
    [loadConversations],
  )

  const handleSend = useCallback(async () => {
    const conversationId = activeIdRef.current
    if (!conversationId) {
      return
    }
    const body = drafts.get(conversationId, 'customer').trim()
    // 只有图片、没有文字也允许发送（故障照片本身就是内容）
    if ((!body && !uploadedImage) || sending || uploading) {
      return
    }
    setSending(true)
    setSendError(null)
    try {
      // 把已上传的图片随消息一起提交：不带 attachmentIds 的话图片永远只是
      // 孤儿附件，消息里看不到、视觉模型也拿不到（实测踩到过）。
      await customerApi.sendMessage(
        conversationId,
        body,
        newClientMessageKey(),
        uploadedImage ? [uploadedImage] : [],
      )
      drafts.clear(conversationId, 'customer')
      if (uploadedImage) imageUpload.clear(uploadedImage)
      await loadMessages(conversationId)
      await loadConversations()
    } catch (error) {
      setSendError(error as ApiError)
    } finally {
      setSending(false)
    }
  }, [drafts, loadConversations, loadMessages, sending, uploadedImage, uploading, imageUpload])

  const handleSendProduct = useCallback(async (product: ProductRef) => {
    const conversationId = activeIdRef.current
    if (!conversationId || sending) return
    setSending(true)
    setSendError(null)
    try {
      await customerApi.sendMessage(conversationId, '', newClientMessageKey(), [], product)
      await loadMessages(conversationId)
      await loadConversations()
    } catch (error) {
      setSendError(error as ApiError)
    } finally {
      setSending(false)
    }
  }, [loadConversations, loadMessages, sending])

  const handleSubmitRating = useCallback(async (value: number | null) => {
    const conversationId = activeIdRef.current
    if (!conversationId || ratingBusy) {
      return
    }
    setRatingBusy(true)
    try {
      const result = value
        ? await customerApi.submitRating(conversationId, 'submit', value)
        : await customerApi.submitRating(conversationId, 'skip')
      setRating({ status: result.ratingStatus, value: result.userRating ?? null })
      setRatingOpen(false)
    } catch (error) {
      setSendError(error as ApiError)
    } finally {
      setRatingBusy(false)
    }
  }, [ratingBusy])

  /**
   * 点击快捷选项：**当作客户消息发出去**，走与手打完全相同的链路。
   *
   * 不做"点按钮才有的特殊分支"：Agent 该追问就追问、该给依据就给依据。
   */
  const handleQuickReply = useCallback(
    async (prompt: string) => {
      const conversationId = activeIdRef.current
      if (!conversationId || sending) {
        return
      }
      setSending(true)
      setSendError(null)
      try {
        await customerApi.sendMessage(conversationId, prompt, newClientMessageKey())
        await loadMessages(conversationId)
        await loadConversations()
      } catch (error) {
        setSendError(error as ApiError)
      } finally {
        setSending(false)
      }
    },
    [loadConversations, loadMessages, sending],
  )

  const listItems = useMemo(
    () =>
      conversations.map((item) => ({
        conversationId: item.conversationId,
        title: item.title,
        preview: item.lastMessagePreview,
        meta: `${item.messageCount} 条消息`,
      })),
    [conversations],
  )

  /* 列表回调必须**引用稳定**，否则 `ConversationList` 的 `memo` 永远命中不了，
     每敲一个字都会把整张列表重渲染一遍（实测 786ms/键，见该组件的注释）。 */
  const handleSelectFromList = useCallback(
    (conversationId: string) => selectConversation(conversationId, { userInitiated: true }),
    [selectConversation],
  )
  const handleCreateClick = useCallback(() => void handleCreate(), [handleCreate])
  const handleRefreshClick = useCallback(() => void loadConversations(), [loadConversations])
  const handleDeleteClick = useCallback(
    (conversationId: string) => void handleDelete(conversationId),
    [handleDelete],
  )
  const handleListDismiss = useCallback(() => setListOpenOverride(false), [setListOpenOverride])

  /**
   * 是否展示快捷入口：本会话**还没有客户消息**时才展示。
   *
   * 这样"用户直接打字"与"点快捷按钮"自然收敛到同一条路径：一旦有了客户消息，
   * 入口就消失，不会一直挂在聊天里当装饰。
   */
  const showQuickReplies =
    messages.length > 0 && !messages.some((item) => item.senderRole === 'customer')

  return (
    <div style={{ display: 'flex', flex: 1, minHeight: 0, minWidth: 0 }}>
      <ConversationList
        items={listItems}
        activeId={activeId}
        loading={loadingList}
        error={listError}
        onSelect={handleSelectFromList}
        onCreate={handleCreateClick}
        onRefresh={handleRefreshClick}
        onDelete={handleDeleteClick}
        emptyText="暂无会话"
        ariaLabel="我的售后会话"
        creating={creating}
        visible={showList}
        overlay={isNarrowList}
        onDismiss={handleListDismiss}
        overlayInset={OVERLAY_LAYOUT.navRailWidth}
        overlayTop={OVERLAY_LAYOUT.bannerHeight}
      />

      <section className="yt-base-panel" style={{ flex: 1 }} aria-label="客户会话内容">
        <CustomerChatHead conversation={activeConversation} aiReplying={aiReplying} transferring={transferring}
          canHandoff={Boolean(activeId) && activeConversation?.serviceMode !== 'operator_assisted'} onHandoff={() => void handoff()}
          showListButton={isNarrowList && !showList} onOpenList={() => setListOpenOverride(true)} />
        <div className="yt-scroll" style={{ flex: 1 }}>
          {loadingMessages && messages.length === 0 ? (
            <div style={{ padding: 24, textAlign: 'center' }}>
              <Spin />
            </div>
          ) : messageError ? (
            <div style={{ padding: 16 }}>
              <Alert
                type="error"
                showIcon
                title="消息加载失败"
                description={messageError}
                action={
                  activeId ? (
                    <Button size="small" onClick={() => void loadMessages(activeId)}>
                      重试
                    </Button>
                  ) : null
                }
              />
            </div>
          ) : (
            <>
              <MessageList messages={messages} conversationId={activeId} viewRole="customer" />
              {/* 开场白之后、客户还没说话时给快捷入口；用户直接打字则自然消失 */}
              {showQuickReplies ? (
                <QuickReplies
                  items={onboarding?.quickReplies ?? []}
                  disabled={sending}
                  onPick={(prompt) => void handleQuickReply(prompt)}
                />
              ) : null}
              <ServiceRating open={ratingOpen} busy={ratingBusy} rating={rating}
                onSubmit={(value) => void handleSubmitRating(value)} />
            </>
          )}
        </div>

        <CustomerComposer conversationId={activeId} draft={draft}
          onDraft={(next) => { if (activeId) drafts.set(activeId, 'customer', next) }}
          onSubmit={() => submitRef.current()} onSendProduct={(product) => void handleSendProduct(product)}
          sending={sending} aiReplying={aiReplying} narrow={isNarrowList} imageUpload={imageUpload}
          sendError={sendError} onClearSendError={() => setSendError(null)} />
      </section>
    </div>
  )
}
