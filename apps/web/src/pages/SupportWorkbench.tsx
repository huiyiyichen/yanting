import {
  CheckOutlined, CloseOutlined, FileTextOutlined, MenuOutlined, ProfileOutlined,
  ReloadOutlined, SearchOutlined, SendOutlined, ThunderboltOutlined, UserOutlined, RobotOutlined, CustomerServiceOutlined,
} from '@ant-design/icons'
import { Sender } from '@ant-design/x'
import { Alert, Avatar, Badge, Button, Collapse, Drawer, Empty, Input, Popconfirm, Segmented, Space, Spin, Tabs, Tag, Tooltip, message } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { deskApi, supportApi, type ConsumerServiceAssistantView, type ConsumerServiceContextView, type MessageView, type ReceptionSnapshot, type TicketView, type ServiceMemoryView } from '../api/client'
import { MessageList } from '../components/MessageList'
import { ChatImageButton, ChatImagePreview, useChatImage } from '../components/ChatImageUpload'
import { QianniuTopbar } from '../components/QianniuTopbar'
import { makeSenderInput } from '../components/SenderParts'
import { useDraftStore } from '../features/conversation/draftStore'
import { newClientMessageKey } from '../features/conversation/messageDirection'
import { OrderFacts, ServiceTimeline, TicketStatus, dateLabel, ticketTypes } from '../features/service-desk/shared'
import { SupportRiskPanel } from '../features/service-desk/SupportRiskPanel'
import { useIsNarrow } from '../hooks/useMediaQuery'
import { emotionLevelLabels, serviceRiskTypeLabels } from '../contracts/enums'
import { emotionStatus } from '../features/service-desk/riskPresentation'
import { handoffBrief } from '../features/service-desk/handoffBrief'

const ComposerInput = makeSenderInput('客服回复输入框')
const styles: Record<string, string> = { recommended: '推荐', concise: '简洁', reassuring: '安抚' }
const memoryLabels = { known: '已知信息', concern: '消费者关注', attempted: '已尝试措施', unresolved: '待解决事项' }
const intentLabels: Record<string, string> = {
  product_question: '商品咨询', order_status: '订单查询', logistics: '物流查询',
  refund: '退款', return: '退货', replacement: '补发换货', adverse_reaction: '使用不适',
  complaint: '投诉', other: '其他诉求', unknown: '待明确',
}
const emotionTagColors: Record<string, string> = { calm: 'success', dissatisfied: 'warning', angry: 'error' }
const riskHref = (conversationId: string, risk: string) =>
  `/risk?${new URLSearchParams({ conversation: conversationId, type: risk }).toString()}`

export function SupportWorkbench() {
  const [params, setParams] = useSearchParams()
  const routeId = params.get('conversation')
  const [fallbackId, setFallbackId] = useState<string | null>(null)
  const id = routeId ?? fallbackId
  const active = useRef(id)
  active.current = id
  const navigate = useNavigate()
  const mobile = useIsNarrow(760)
  const compact = useIsNarrow(1180)
  const [queueOpen, setQueueOpen] = useState(false)
  const [pluginOpen, setPluginOpen] = useState(false)
  const [pluginTab, setPluginTab] = useState('assistant')
  const [snapshot, setSnapshot] = useState<ReceptionSnapshot | null>(null)
  const [mode, setMode] = useState('全部')
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState<MessageView[]>([])
  const [context, setContext] = useState<ConsumerServiceContextView | null>(null)
  const [tickets, setTickets] = useState<TicketView[]>([])
  const [assistant, setAssistant] = useState<ConsumerServiceAssistantView | null>(null)
  const [memory, setMemory] = useState<ServiceMemoryView | null>(null)
  const [error, setError] = useState('')
  const [queueError, setQueueError] = useState('')
  const [aiError, setAiError] = useState('')
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [sending, setSending] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [toast, holder] = message.useMessage()
  const drafts = useDraftStore()
  const draft = id ? drafts.get(id, 'support') : ''
  const revision = useRef(new Map<string, number>())
  const detailRequest = useRef(0)
  const assistantRequest = useRef(0)
  const queueUnavailable = useRef(false)
  const current = snapshot?.items.find((item) => item.conversationId === id)
  const automatic = current?.serviceMode === 'autonomous'
  const aiReplying = automatic && ['queued', 'running'].includes(current?.autoReplyStatus ?? '')
  const imageUpload = useChatImage(id, supportApi.uploadAttachment)
  const uploading = imageUpload.image?.uploading ?? false
  const attachmentId = imageUpload.image?.attachment?.attachmentId
  const sendRef = useRef<() => void>(() => undefined)
  sendRef.current = () => { void send() }

  const loadDetail = useCallback(async (target: string) => {
    const request = ++detailRequest.current
    const analysisVersion = assistantRequest.current
    try {
      const [rows, facts, cached, work, remembered] = await Promise.all([
        supportApi.receptionMessages(target), supportApi.serviceContext(target),
        supportApi.assistant(target), deskApi.tickets(target), supportApi.memory(target),
      ])
      if (active.current !== target || request !== detailRequest.current) return
      setMessages(rows); setContext(facts); setTickets(work); setMemory(remembered); setError('')
      if (analysisVersion === assistantRequest.current) setAssistant(cached)
      await supportApi.markSeen(target, rows.at(-1)?.messageRevision ?? 0)
    } catch (err) {
      if (active.current === target) setError((err as Error).message)
    } finally {
      if (active.current === target) setLoading(false)
    }
  }, [])

  useEffect(() => {
    setMessages([]); setContext(null); setAssistant(null); setTickets([]); setMemory(null); setAiError('')
    if (id) { setLoading(true); void loadDetail(id) }
  }, [id, loadDetail])

  useEffect(() => {
    let disposed = false
    let running = false
    const sync = async () => {
      if (running || document.hidden) return
      running = true
      try {
        const next = await supportApi.reception()
        if (disposed) return
        setSnapshot(next)
        setQueueError('')
        if (queueUnavailable.current && active.current) void loadDetail(active.current)
        queueUnavailable.current = false
        const initialized = revision.current.size > 0
        for (const item of next.items) {
          const previous = revision.current.get(item.conversationId)
          const changed = initialized && (previous === undefined ? item.messageRevision > 0 : previous !== item.messageRevision)
          if (changed && item.conversationId === active.current) void loadDetail(item.conversationId)
          if (changed && item.unreadCount && item.conversationId !== active.current) {
            void toast.info({ content: `新消息 · ${item.buyerAlias}`, key: item.conversationId })
          }
          revision.current.set(item.conversationId, item.messageRevision)
        }
        if (!active.current && next.items.length) {
          const firstId = next.items[0].conversationId
          setFallbackId(firstId)
          setParams({ conversation: firstId }, { replace: true })
        }
      } catch (err) {
        if (!disposed) {
          queueUnavailable.current = true
          setQueueError((err as Error).message)
        }
      }
      finally { running = false }
    }
    void sync()
    const timer = window.setInterval(() => void sync(), 1500)
    window.addEventListener('focus', sync)
    return () => { disposed = true; clearInterval(timer); window.removeEventListener('focus', sync) }
  }, [loadDetail, setParams, toast])

  const generate = async (target = id) => {
    if (!target || generating) return
    assistantRequest.current++
    setGenerating(true); setAiError('')
    try {
      await supportApi.generateAssistant(target)
      const [cached, remembered] = await Promise.all([supportApi.assistant(target), supportApi.memory(target)])
      if (active.current === target) { setAssistant(cached); setMemory(remembered) }
    } catch (err) { if (active.current === target) setAiError((err as Error).message) }
    finally { setGenerating(false) }
  }
  const send = async () => {
    if (!id || (!draft.trim() && !attachmentId) || automatic || sending || uploading) return
    const target = id, body = draft
    setSending(true)
    try {
      await supportApi.sendReceptionMessage(target, body, newClientMessageKey(), imageUpload.attachmentIds)
      if (drafts.get(target, 'support') === body) drafts.clear(target, 'support')
      if (attachmentId) imageUpload.clear(attachmentId)
      await loadDetail(target)
    } catch (err) { if (active.current === target) setError((err as Error).message) }
    finally { setSending(false) }
  }
  const switchMode = async (mode: 'autonomous' | 'operator_assisted') => {
    if (!id) return
    const origin = id
    setSwitching(true)
    try {
      await supportApi.setReceptionMode(origin, mode)
      setSnapshot(await supportApi.reception())
      await loadDetail(origin)
      if (mode === 'operator_assisted' && active.current === origin) {
        setPluginTab('assistant')
        if (compact) setPluginOpen(true)
        await generate(origin)
      }
    } catch (err) { setError((err as Error).message) }
    finally { setSwitching(false) }
  }
  const adopt = async (style: string, body: string, action: 'adopt' | 'ignore') => {
    if (!id || !assistant) return
    const target = id
    try {
      await supportApi.assistantAction(target, assistant.inputHash ?? '', style, action)
      if (active.current !== target) return
      if (action === 'adopt') {
        drafts.set(target, 'support', body)
        setAssistant((old) => old ? { ...old, adoptedCount: (old.adoptedCount ?? 0) + 1 } : old)
        setPluginOpen(false)
        void toast.success('已填入回复框')
      }
      else setAssistant((old) => old ? { ...old, replySuggestions: old.replySuggestions.filter((r) => r.style !== style) } : old)
    } catch (err) { if (active.current === target) setAiError((err as Error).message) }
  }

  const queueItems = (snapshot?.items ?? []).filter((item) =>
    (mode !== '未读' || item.unreadCount > 0)
    && (mode !== '人工' || item.serviceMode === 'operator_assisted')
    && (mode !== '历史' || item.dataSource === 'imported')
    && `${item.buyerAlias} ${item.conversationId} ${item.preview}`.includes(query))
  const queue = <div className="reception-queue">
    <div className="reception-queue-head">
      <div className="section-title-row"><h2>会话</h2><Badge count={snapshot?.unreadTotal ?? 0} /></div>
      <Input prefix={<SearchOutlined />} placeholder="客户、会话、消息" aria-label="搜索会话" value={query} allowClear onChange={(e) => setQuery(e.target.value)} />
      <Segmented block options={['全部', '人工', '未读', '历史']} value={mode} onChange={setMode} />
    </div>
    <div className="reception-list">{queueItems.map((item) => <div key={item.conversationId}
      className={`reception-row-item${id === item.conversationId ? ' is-active' : ''}`}>
      <button className={`reception-row${id === item.conversationId ? ' is-active' : ''}`}
        aria-label={`${item.buyerAlias} ${item.conversationId}`}
        onClick={() => { setParams({ conversation: item.conversationId }); setQueueOpen(false) }}>
        <Badge count={item.unreadCount} size="small"><Avatar icon={<UserOutlined />} /></Badge>
        <span className="reception-row-main">
          <span className="reception-row-title"><strong>{item.buyerAlias}</strong><time>{dateLabel(item.updatedAt)}</time></span>
          <span className="reception-row-preview">{item.serviceMode === 'autonomous' ? 'AI · ' : '人工 · '}{item.preview || '新会话'}</span>
          <span className="reception-row-status">
            {item.currentEmotion ? <Tag color={emotionTagColors[item.currentEmotion]}>{emotionLevelLabels[item.currentEmotion]}</Tag> : null}
            {item.riskLevel === 'high' ? <Tag color="error">高风险</Tag> : null}
          </span>
        </span>
      </button>
      {item.activeRiskTypes?.length || item.reviewRiskTypes?.length ? <div className="reception-risk-links">
        {item.activeRiskTypes?.slice(0, 2).map((risk) => <Link key={risk} to={riskHref(item.conversationId, risk)}
          aria-label={`查看${serviceRiskTypeLabels[risk]} · ${item.buyerAlias}`}>
          <Tag color="warning">{serviceRiskTypeLabels[risk]}</Tag>
        </Link>)}
        {item.reviewRiskTypes?.slice(0, 1).map((risk) => <Link key={`review-${risk}`} to={riskHref(item.conversationId, risk)}
          aria-label={`复核${serviceRiskTypeLabels[risk]} · ${item.buyerAlias}`}>
          <Tag color="processing">待复核 · {serviceRiskTypeLabels[risk]}</Tag>
        </Link>)}
      </div> : null}
    </div>)}
      {!queueItems.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" />}
    </div>
  </div>

  const riskRefreshKey = [
    current?.messageRevision ?? 0, current?.modeRevision ?? 0,
    current?.activeRiskTypes?.join(',') ?? '', current?.reviewRiskTypes?.join(',') ?? '',
  ].join('|')
  const brief = handoffBrief(assistant, messages)
  const refreshAfterIntervention = async (target: string) => {
    if (active.current !== target) return
    setSnapshot(await supportApi.reception())
    await loadDetail(target)
    if (active.current === target) await generate(target)
  }
  const plugin = (visible: boolean) => <div className="desk-plugin-inner">
    <Tabs size="small" activeKey={pluginTab} onChange={setPluginTab} items={[
      { key: 'assistant', label: 'AI 辅助', children: <>
        <section className="service-section" aria-label="交接摘要">
          <div className="section-title-row"><h3>交接摘要</h3><Button size="small" icon={<ThunderboltOutlined />} loading={generating} disabled={!id}
            onClick={() => void generate()}>{assistant ? '重新生成' : '生成建议'}</Button></div>
          {brief.map((line, index) => <p key={index}>{line}</p>)}
          {!brief.length && <Tag>暂无咨询</Tag>}
          {assistant && !assistant.stale ? <Space wrap><Tag>{intentLabels[assistant.intent ?? 'unknown'] ?? '待明确'}</Tag>
            <Tag color={emotionTagColors[assistant.emotionLevel]}>{emotionStatus({ currentEmotion: assistant.emotionLevel, emotionTrend: assistant.emotionTrend })}</Tag>
          </Space> : null}
        </section>
        {aiError && <Alert type="error" title={aiError} showIcon />}
        <section className="service-section"><div className="section-title-row"><h3>回复建议</h3>
          {assistant ? <Tag color="success">已采用 {assistant.adoptedCount ?? 0} 条</Tag> : null}
        </div>
          {assistant?.stale && <Tag color="warning">待更新</Tag>}
          {assistant && !assistant.stale ? assistant.replySuggestions.map((item) => <article className="reply-candidate" key={item.style}>
            <div className="reply-candidate-head"><Tag>{styles[item.style] ?? item.style}</Tag>
              <Space size={4} wrap>{item.empathyDimensions?.map((dimension) => <Tag
                key={dimension.key} color={dimension.status === 'present' ? 'success' : 'default'}
                title={dimension.reason}>{dimension.label}</Tag>)}</Space>
            </div><p>{item.body}</p><Space>
              <Button size="small" icon={<CheckOutlined />} disabled={automatic || assistant.verificationStatus !== 'verified'} onClick={() => void adopt(item.style, item.body, 'adopt')}>采用</Button>
              <Button size="small" icon={<CloseOutlined />} onClick={() => void adopt(item.style, item.body, 'ignore')}>忽略</Button>
            </Space>
          </article>) : <Tag>{generating ? '生成中' : '待生成'}</Tag>}
        </section>
        {id ? <SupportRiskPanel key={id} conversationId={id}
          enabled={visible && pluginTab === 'assistant'} refreshKey={riskRefreshKey}
          serviceMode={current?.serviceMode} onIntervened={refreshAfterIntervention} /> : null}
        {context?.historyServices?.length ? <section className="service-section">
          <div className="section-title-row"><h3>消费者服务档案</h3>
            <Button size="small" onClick={() => { setPluginTab('history'); if (compact) setPluginOpen(true) }}>
              查看完整轨迹
            </Button>
          </div>
          {assistant && (assistant.adoptedCount ?? 0) > 0
            ? <Tag color="success">本次已采用 {assistant.adoptedCount} 条 AI 建议</Tag>
            : null}
          <div className="consumer-history-card">
            <div className="consumer-history-summary">
              <strong>{context.historyServices.length} 次历史进线</strong>
              <span>{context.historyServices.filter((item) => item.relation === 'same_order').length} 次同订单</span>
            </div>
            {context.historyServices.slice(0, 3).map((item) => <article key={item.conversationId}
              className={`consumer-history-item${item.relation === 'same_order' ? ' is-related' : ''}`}>
              <div className="consumer-history-item-head">
                <Space size={4}>
                  <strong>{item.relation === 'same_order' ? '同订单服务' : '历史服务'}</strong>
                  {item.sameTopic === true && <Tag color="processing">同一诉求</Tag>}
                  {item.sameTopic === false && <Tag>不同诉求</Tag>}
                </Space>
                <time>{dateLabel(item.lastAt ?? item.firstAt)}</time>
              </div>
              <p>{item.latestCustomerMessage || '暂无消费者原话'}</p>
              {item.latestStaffMessage && <span>客服曾回复：{item.latestStaffMessage}</span>}
            </article>)}
          </div>
        </section> : null}
        {assistant ? <Collapse ghost items={[{ key: 'details', label: '更多信息', children: <>
          {assistant.groundingSources?.some((source) => source.kind === 'image_observation') ? <section className="service-section">
            <h3>图片可见信息</h3>
            {assistant.groundingSources.filter((source) => source.kind === 'image_observation').map((source) => (
              <div className="evidence-quote" key={source.sourceId}>
                <p>{source.text}</p>
                {typeof source.fields?.attachmentId === 'string' && <a
                  href={`/api/customer/attachments/${encodeURIComponent(source.fields.attachmentId)}/content`}
                  target="_blank" rel="noreferrer">查看原图</a>}
              </div>
            ))}
          </section> : null}
          {assistant.personalizedAdvice?.length ? <section className="service-section">
            <h3>个性化建议</h3>
            {assistant.personalizedAdvice.map((item) => <article className="reply-candidate" key={`${item.category}-${item.title}`}>
              <Tag color={item.category === 'product_selection' ? 'warning' : 'processing'}>{item.title}</Tag>
              {item.productName ? <strong>{item.productName}</strong> : null}
              {item.productSku ? <Tag>{item.productSku}</Tag> : null}
              <p>{item.action}</p>
              <small>{item.rationale}</small>
              {item.evidence?.map((evidence) => <blockquote className="evidence-quote" key={`${evidence.sourceRef}-${evidence.quote}`}>
                <small>{evidence.label}</small><p>{evidence.quote}</p>
              </blockquote>)}
            </article>)}
          </section> : null}
          <section className="service-section"><h3>下一步</h3>{assistant.nextSteps.map((step) => <p key={step}>{step}</p>)}
            {assistant.missingInformation.map((item) => <Tag key={item}>待确认：{item}</Tag>)}</section>
          <section className="service-section"><h3>知识依据</h3>{assistant.knowledgeEvidence?.length ? assistant.knowledgeEvidence.map((item, i) => <div className="evidence-quote" key={i}>
            <strong>{String(item.document_title ?? '')}</strong><p>{String(item.quoted_excerpt ?? '')}</p>
          </div>) : <Tag>{assistant.knowledgeStatus === 'failed' ? '检索失败' : '依据不足'}</Tag>}</section>
        </> }]} /> : null}
      </> },
      { key: 'memory', label: '服务记忆', children: <>
        {memory?.stale && <Tag color="warning">待更新</Tag>}
        {Object.entries(memoryLabels).map(([category, label]) => <section className="service-section" key={category}>
          <h3>{label}</h3>{memory?.items?.filter((item) => item.category === category).map((item, index) => {
            const source = memory.sources?.find((s) => s.sourceId === item.sourceRef)
            return <blockquote className="evidence-quote" key={`${item.sourceRef}-${index}`}>
              {item.label && <strong>{item.label}</strong>}<p>{item.quote}</p>
              <small>{source?.label ?? '原始来源'} · {dateLabel(source?.occurredAt)}</small>
            </blockquote>
          })}
          {!memory?.items?.some((item) => item.category === category) && <Tag>暂无记录</Tag>}
        </section>)}
      </> },
      { key: 'orders', label: `订单 ${context?.orders.length ?? 0}`, children: <OrderFacts context={context} /> },
      { key: 'tickets', label: `工单 ${tickets.length}`, children: <>
        <Button icon={<FileTextOutlined />} disabled={!id} onClick={() => navigate(`/platform/work-orders?conversation=${id}&create=1`)}>新建工单</Button>
        {tickets.map((t) => <section className="service-section" key={t.ticketId}><div className="section-title-row"><strong>{ticketTypes[t.workOrderType]}</strong><TicketStatus status={t.status} /></div>
          <p>{t.ticketId}</p><p>{t.assignee || '待分配'}</p><Button size="small" onClick={() => navigate(`/platform/work-orders?ticket=${t.ticketId}`)}>查看详情</Button>
        </section>)}
      </> },
      { key: 'history', label: '轨迹', children: <>
        <ServiceTimeline context={context} />
        {context?.historyServices?.length ? <section className="service-section">
          <div className="section-title-row"><h3>历史服务</h3><Tag>{context.historyServices.length} 次</Tag></div>
          {context.historyServices.map((item) => <article className="consumer-history-item" key={item.conversationId}>
            <div className="consumer-history-item-head">
              <strong>{item.conversationId}</strong>
              <time>{dateLabel(item.lastAt ?? item.firstAt)}</time>
            </div>
            <p>{item.latestCustomerMessage || '暂无消费者原话'}</p>
            {item.latestStaffMessage && <span>客服曾回复：{item.latestStaffMessage}</span>}
            <span>订单 {item.orderIds?.length ?? 0} · 工单 {item.workOrderIds?.length ?? 0}</span>
          </article>)}
        </section> : null}
      </> },
    ]} />
  </div>
  return <div className="desk-workbench">
    {holder}
    <QianniuTopbar title="客服工作台" stats={[
      { label: '会话', value: snapshot?.items.length ?? 0 }, { label: '未读', value: snapshot?.unreadTotal ?? 0, warning: true },
      { label: '人工会话', value: snapshot?.items.filter((c) => c.dataSource === 'live' && c.serviceMode === 'operator_assisted').length ?? 0 },
      { label: '未结工单', value: tickets.filter((t) => t.status !== 'resolved').length },
    ]} />
    <div className="reception-workspace">
      {!mobile && queue}
      <section className="reception-chat" aria-label="客服对话">
        <header className="anker-chat-head anker-hairline-bottom">
          {mobile && <Button icon={<MenuOutlined />} aria-label="会话列表" onClick={() => setQueueOpen(true)} />}
          <Avatar icon={<UserOutlined />} /><strong className="chat-buyer">{current?.buyerAlias ?? '未选择会话'}</strong>
          {current && <Tag color={automatic ? 'processing' : 'default'}>{aiReplying ? 'AI 回复中' : automatic ? 'AI 接待' : '人工接待'}</Tag>}
          {current?.currentEmotion && <Tag color={emotionTagColors[current.currentEmotion]}>{emotionLevelLabels[current.currentEmotion]}</Tag>}
          {current?.riskLevel === 'high' && <Tag color="error">高风险</Tag>}
          <Tooltip title="刷新会话"><Button type="text" aria-label="刷新会话" icon={<ReloadOutlined />} disabled={!id} onClick={() => id && void loadDetail(id)} /></Tooltip>
          {compact && <Button icon={<ProfileOutlined />} aria-label="接待辅助" onClick={() => setPluginOpen(true)} />}
        </header>
        {id && <div className="reception-modebar">
          {automatic
            ? <Button size="small" icon={<CustomerServiceOutlined />} aria-label="接管会话" loading={switching} onClick={() => void switchMode('operator_assisted')}>接管会话</Button>
            : <Popconfirm title="恢复 AI 自动接待？" okText="恢复" cancelText="取消" onConfirm={() => void switchMode('autonomous')}>
              <Button size="small" icon={<RobotOutlined />} aria-label="恢复 AI 接待" loading={switching}>恢复 AI 接待</Button>
            </Popconfirm>}
          {current?.handoffReason && <Tag color="warning">{current.handoffReason}</Tag>}
        </div>}
        {current && (current.activeRiskTypes?.length || current.reviewRiskTypes?.length) ? <div className="reception-riskbar">
          {current.activeRiskTypes?.map((risk) => <Link key={risk} to={riskHref(current.conversationId, risk)}
            aria-label={`查看当前${serviceRiskTypeLabels[risk]}`}>
            <Tag color="warning">{serviceRiskTypeLabels[risk]}</Tag>
          </Link>)}
          {current.reviewRiskTypes?.map((risk) => <Link key={`review-${risk}`} to={riskHref(current.conversationId, risk)}
            aria-label={`复核当前${serviceRiskTypeLabels[risk]}`}>
            <Tag color="processing">待复核 · {serviceRiskTypeLabels[risk]}</Tag>
          </Link>)}
        </div> : null}
        {context?.orders[0] && <button className="chat-order-strip" onClick={() => { setPluginTab('orders'); if (compact) setPluginOpen(true) }}>
          <FileTextOutlined /><span>{context.orders[0].productName}</span><Tag>{context.orders[0].sourceStatus}</Tag>
        </button>}
        {(error || queueError) && <Alert type="error" title={error || queueError} showIcon
          action={<Button size="small" onClick={() => window.location.reload()}>刷新</Button>} />}
        <div className="anker-scroll chat-message-surface">{loading ? <Spin /> : <MessageList messages={messages} viewRole="support" />}</div>
        <div className="anker-composer anker-hairline-top">
          {imageUpload.image?.error && <Alert type="error" showIcon title={imageUpload.image.error}
            closable={{ onClose: () => imageUpload.clear() }} />}
          <ChatImagePreview image={imageUpload.image} onRemove={() => imageUpload.clear()}
            disabled={sending || uploading} />
          <div className="composer-actions">
            <ChatImageButton upload={imageUpload.upload} disabled={!id || automatic || sending || uploading}
              uploading={uploading} />
            <Button type="text" icon={<FileTextOutlined />} disabled={!id} onClick={() => navigate(`/platform/work-orders?conversation=${id}&create=1`)}>建工单</Button>
            <Button type="text" icon={<ThunderboltOutlined />} disabled={!id} loading={generating} onClick={() => { setPluginTab('assistant'); if (compact) setPluginOpen(true); void generate() }}>AI 建议</Button></div>
          <Sender value={draft} components={{ input: ComposerInput }} placeholder="回复客户"
            onChange={(value) => id && drafts.set(id, 'support', value)} onSubmit={() => sendRef.current()}
            onPasteFile={(files) => { if (files[0]) void imageUpload.upload(files[0]) }}
            submitType="enter" disabled={!id || automatic || sending} loading={sending}
            suffix={(_, { components }) => <components.SendButton type="primary" shape="default"
              aria-label="发送" icon={<SendOutlined />}
              disabled={!id || (!draft.trim() && !attachmentId) || automatic || sending || uploading}
              loading={sending} />} />
        </div>
      </section>
      {!compact && <aside className="reception-plugin" aria-label="接待辅助信息">{plugin(true)}</aside>}
    </div>
    <Drawer title="会话" placement="left" size={300} open={queueOpen} onClose={() => setQueueOpen(false)}>{queue}</Drawer>
    <Drawer title="接待辅助" size={460} open={pluginOpen} onClose={() => setPluginOpen(false)}>{plugin(pluginOpen)}</Drawer>
  </div>
}
