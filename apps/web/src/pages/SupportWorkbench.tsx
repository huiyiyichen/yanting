import {
  FileTextOutlined, MenuOutlined, ProfileOutlined, ReloadOutlined,
  SearchOutlined, SendOutlined, ThunderboltOutlined, } from '@ant-design/icons'
import { Sender } from '@ant-design/x'
import { Alert, Button, Tooltip, Drawer, Empty, Input, Segmented, Spin, Tabs, Tag, message } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { deskApi, supportApi, type ConsumerServiceAssistantView, type ConsumerServiceContextView, type MessageView, type ReceptionSnapshot, type TicketView, type ServiceMemoryView, type ConsumerProfileView, type ReceptionStatsView } from '../api/client'
import { MessageList } from '../components/MessageList'
import { ChatImageButton, ChatImagePreview, useChatImage } from '../components/ChatImageUpload'
import { QianniuTopbar } from '../components/QianniuTopbar'
import { makeSenderInput } from '../components/SenderParts'
import { useDraftStore } from '../features/conversation/draftStore'
import { newClientMessageKey } from '../features/conversation/messageDirection'
import { OrderFacts, ServiceTimeline, TicketStatus, dateLabel, ticketTypes } from '../features/service-desk/shared'
import { SupportRiskPanel } from '../features/service-desk/SupportRiskPanel'
import { escalationMessage, messageEmotions } from '../features/service-desk/messageEmotion'
import { AiReceptionBar, ChatHead } from '../features/service-desk/ChatHead'
import { QueueRow } from '../features/service-desk/QueueRow'
import { DeskProductCard } from '../features/service-desk/DeskProductCard'
import { PersonaCard } from '../features/service-desk/PersonaCard'
import { shouldHoldSend, useDraftReview } from '../features/service-desk/draftReview'
import { serviceMetricStats } from '../features/service-desk/serviceMetrics'
import { TicketDraftDrawer } from '../features/service-desk/TicketDraftDrawer'
import { ReplyCard } from '../features/service-desk/ReplyCard'
import { EvidenceFolds, IntentRow, NextSteps } from '../features/service-desk/AssistBlocks'
import { useIsNarrow } from '../hooks/useMediaQuery'
import { handoffBrief } from '../features/service-desk/handoffBrief'

const ComposerInput = makeSenderInput('客服回复输入框')
const memoryLabels = { known: '已知信息', concern: '消费者关注', attempted: '已尝试措施', unresolved: '待解决事项' }
const intentLabels: Record<string, string> = {
  product_question: '商品咨询', order_status: '订单查询', logistics: '物流查询',
  refund: '退款', return: '退货', replacement: '补发换货', adverse_reaction: '使用不适',
  complaint: '投诉', other: '其他诉求', unknown: '待明确',
}

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
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 30000); return () => window.clearInterval(timer) }, [])
  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState<MessageView[]>([])
  const [context, setContext] = useState<ConsumerServiceContextView | null>(null)
  const [tickets, setTickets] = useState<TicketView[]>([])
  const [assistant, setAssistant] = useState<ConsumerServiceAssistantView | null>(null)
  const [memory, setMemory] = useState<ServiceMemoryView | null>(null)
  const [profile, setProfile] = useState<ConsumerProfileView | null>(null)
  const [metrics, setMetrics] = useState<ReceptionStatsView | null>(null)
  const [ticketDrawer, setTicketDrawer] = useState(false)
  const [stages, setStages] = useState<{ name: string; status: string }[]>([])
  useEffect(() => {
    let cancelled = false
    const read = () => { if (!document.hidden) deskApi.stats().then((next) => { if (!cancelled) setMetrics(next?.handoffs ? next : null) }).catch(() => undefined) }
    read()
    const timer = window.setInterval(read, 15000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [])
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
  const draftFindings = useDraftReview(id ?? undefined, draft, !automatic)
  const aiReplying = automatic && ['queued', 'running'].includes(current?.autoReplyStatus ?? '')
  const imageUpload = useChatImage(id, supportApi.uploadAttachment)
  const uploading = imageUpload.image?.uploading ?? false
  const attachmentId = imageUpload.image?.attachment?.attachmentId
  const acknowledgedDraft = useRef<string | null>(null)
  const sendRef = useRef<() => void>(() => undefined)
  sendRef.current = () => { void send() }

  const loadDetail = useCallback(async (target: string) => {
    const request = ++detailRequest.current
    const analysisVersion = assistantRequest.current
    try {
      const [rows, facts, cached, work, remembered, persona] = await Promise.all([
        supportApi.receptionMessages(target), supportApi.serviceContext(target),
        supportApi.assistant(target), deskApi.tickets(target), supportApi.memory(target),
        supportApi.profile(target).catch(() => null),
      ])
      if (active.current !== target || request !== detailRequest.current) return
      setMessages(rows); setContext(facts); setTickets(work); setMemory(remembered); setProfile(persona); setError('')
      if (analysisVersion === assistantRequest.current) setAssistant(cached)
      await supportApi.markSeen(target, rows.at(-1)?.messageRevision ?? 0)
    } catch (err) {
      if (active.current === target) setError((err as Error).message)
    } finally {
      if (active.current === target) setLoading(false)
    }
  }, [])

  useEffect(() => {
    setMessages([]); setContext(null); setAssistant(null); setTickets([]); setMemory(null); setProfile(null); setAiError('')
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

  const generate = async (target = id, style?: string) => {
    if (!target || generating) return
    const request = ++assistantRequest.current
    setGenerating(true); setAiError(''); setStages([])
    try {
      let failure = ''
      await supportApi.streamAssistant(target, style, (event) => {
        if (active.current !== target || request !== assistantRequest.current) return
        if (event.type === 'stage') setStages((old) => [...old.filter((item) => item.name !== event.name), { name: event.name, status: event.status }])
        else if (event.type === 'done') setAssistant(event.view)
        else failure = event.message
      })
      if (failure) throw new Error(failure)
      const remembered = await supportApi.memory(target)
      if (active.current === target) setMemory(remembered)
    } catch (err) { if (active.current === target) setAiError((err as Error).message) }
    finally { setGenerating(false) }
  }
  const send = async () => {
    if (!id || (!draft.trim() && !attachmentId) || automatic || sending || uploading) return
    if (shouldHoldSend(draftFindings, draft, acknowledgedDraft.current)) {
      acknowledgedDraft.current = draft
      void toast.warning({ content: draftFindings.find((item) => item.severity === 'high')?.label, key: 'draft-review' })
      return
    }
    acknowledgedDraft.current = null
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
  const adopt = async (style: string, body: string, action: 'adopt' | 'adopt_edited' | 'ignore') => {
    if (!id || !assistant) return
    const target = id
    try {
      await supportApi.assistantAction(target, assistant.inputHash ?? '', style, action, action === 'adopt_edited' ? body : undefined)
      if (active.current !== target) return
      if (action !== 'ignore') {
        drafts.set(target, 'support', body)
        setAssistant((old) => old ? { ...old, adoptedCount: (old.adoptedCount ?? 0) + 1 } : old)
        setPluginOpen(false)
        void toast.success('已填入回复框')
      }
      else setAssistant((old) => old ? { ...old, replySuggestions: old.replySuggestions.filter((r) => r.style !== style) } : old)
    } catch (err) { if (active.current === target) setAiError((err as Error).message) }
  }
  const rewrite = async (style: string, body: string, instruction: 'gentler' | 'concise' | 'professional') => {
    if (!id) throw new Error('未选择会话')
    return (await supportApi.rewriteSuggestion(id, style, body, instruction)).text
  }

  const emotionsById = useMemo(() => messageEmotions(profile, id), [profile, id])
  const escalationId = useMemo(() => escalationMessage(profile, id), [profile, id])
  const queueItems = (snapshot?.items ?? []).filter((item) =>
    (mode !== '未读' || item.unreadCount > 0)
    && (mode !== '人工' || item.serviceMode === 'operator_assisted')
    && (mode !== '风险' || Boolean(item.activeRiskTypes?.length || item.reviewRiskTypes?.length))
    && `${item.buyerAlias} ${item.conversationId} ${item.preview}`.includes(query))
  const allItems = snapshot?.items ?? []
  const queueCounts: Record<string, number> = {
    人工: allItems.filter((item) => item.serviceMode === 'operator_assisted').length,
    风险: allItems.filter((item) => item.activeRiskTypes?.length || item.reviewRiskTypes?.length).length,
  }
  const queue = <div className="reception-queue">
    <div className="reception-queue-head">
      <Input variant="filled" prefix={<SearchOutlined />} placeholder="客户、订单号、聊天记录" aria-label="搜索会话" value={query} allowClear onChange={(e) => setQuery(e.target.value)} />
      <Segmented className="yt-qtabs" options={(['全部', '人工', '风险', '未读'] as const).map((value) => ({ value,
        label: <>{value}{queueCounts[value] ? <span className="n">{queueCounts[value]}</span> : null}</> }))} value={mode} onChange={setMode} />
    </div>
    <div className="reception-list">{queueItems.length ? <div className="yt-queue-group"><span>正在接待</span><span>最近消息</span></div> : null}
      {queueItems.map((item) => <QueueRow key={item.conversationId} item={item} active={id === item.conversationId} now={now}
        onOpen={() => { setParams({ conversation: item.conversationId }); setQueueOpen(false) }} />)}
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
    <Tabs size="small" className="yt-ptabs" activeKey={pluginTab} onChange={setPluginTab}
      tabBarExtraContent={{
        left: <span className="yt-pbrand"><span className="yt-wave" aria-hidden="true"><i /><i /><i /><i /><i /></span>颜听</span>,
        right: <Tooltip title={assistant ? '重新生成' : '生成建议'}><Button type="text" className="yt-pbar-btn"
          aria-label={assistant ? '重新生成' : '生成建议'} icon={<ReloadOutlined />} loading={generating} disabled={!id}
          onClick={() => void generate()} /></Tooltip>,
      }} items={[
      { key: 'assistant', label: '辅助', children: <>
        {profile?.memory && profile.conversationId === id ? <PersonaCard profile={profile} /> : null}
        {assistant && !assistant.stale ? <IntentRow primary={intentLabels[assistant.intent ?? 'unknown']}
          items={profile?.conversationId === id ? (profile?.memory.pending ?? []).map((item) => item.text) : []}
          missing={assistant.missingInformation} /> : null}
        {aiError && <Alert type="error" title={aiError} showIcon />}
        {!(assistant && !assistant.stale && assistant.replySuggestions.length) && <section className="service-section yt-card" aria-label="交接摘要">
          <h3>交接摘要</h3>
          {brief.map((line, index) => <p key={index}>{line}</p>)}
          {!brief.length && <p className="yt-empty">暂无咨询</p>}
        </section>}
        {assistant && !assistant.stale && assistant.replySuggestions.length ? <>
          {assistant.verificationStatus === 'partial' && <Tag color="warning">
            已移除 {Number(assistant.modelUsage?.segmentsDropped ?? 0)} 段
          </Tag>}
          <ReplyCard key={`${id}-${assistant.inputHash}`}
            suggestions={assistant.replySuggestions} automatic={automatic} generating={generating}
            adoptable={['verified', 'partial'].includes(assistant.verificationStatus ?? '')}
            onAdopt={(style, body, edited) => void adopt(style, body, edited ? 'adopt_edited' : 'adopt')}
            onIgnore={(style) => void adopt(style, '', 'ignore')}
            onRegenerate={(style) => void generate(id, style)} onRewrite={rewrite} />
        </> : <section className="service-section yt-card yt-reply-empty" aria-label="回复建议">
          <h3>回复建议<span className="r">{assistant?.stale ? '待更新' : generating ? '生成中' : '待生成'}</span></h3>
          {generating && stages.length > 0 && <ol className="yt-stages" aria-label="生成进度">
            {stages.map((item) => <li key={item.name} className={`is-${item.status}`}>{item.name}</li>)}
          </ol>}
        </section>}
        {id ? <SupportRiskPanel key={id} conversationId={id}
          enabled={visible && pluginTab === 'assistant'} refreshKey={riskRefreshKey}
          serviceMode={current?.serviceMode} onIntervened={refreshAfterIntervention} /> : null}
        {assistant && !assistant.stale ? <NextSteps scope={`${id}:${assistant.inputHash}`} steps={assistant.nextSteps} /> : null}
        <EvidenceFolds folds={[
          { key: 'knowledge', label: '知识依据', icon: 'knowledge', count: assistant?.knowledgeEvidence?.length ?? 0,
            body: assistant?.knowledgeEvidence?.length ? assistant.knowledgeEvidence.map((item, i) => <div className="evidence-quote" key={i}>
              <strong>{String(item.document_title ?? '')}</strong><p>{String(item.quoted_excerpt ?? '')}</p>
            </div>) : <p className="yt-empty">{assistant?.knowledgeStatus === 'failed' ? '检索失败' : '依据不足'}</p> },
          { key: 'orders', label: '订单与物流', icon: 'order', count: context?.orders.length ?? 0, body: <OrderFacts context={context} /> },
          { key: 'tickets', label: '售后工单', icon: 'ticket', count: tickets.length, body: tickets.map((t) => <div className="yt-fold-row" key={t.ticketId}>
            <strong>{ticketTypes[t.workOrderType]}</strong><span>{t.ticketId}</span><TicketStatus status={t.status} />
            <Button size="small" type="link" onClick={() => navigate(`/platform/work-orders?ticket=${t.ticketId}`)}>查看</Button>
          </div>) },
          { key: 'images', label: '图片可见信息', icon: 'image',
            count: assistant?.groundingSources?.filter((source) => source.kind === 'image_observation').length ?? 0,
            body: assistant?.groundingSources?.filter((source) => source.kind === 'image_observation').map((source) => (
              <div className="evidence-quote" key={source.sourceId}>
                <p>{source.text}</p>
                {typeof source.fields?.attachmentId === 'string' && <a
                  href={`/api/customer/attachments/${encodeURIComponent(source.fields.attachmentId)}/content`}
                  target="_blank" rel="noreferrer">查看原图</a>}
              </div>)) },
          { key: 'advice', label: '个性化建议', icon: 'advice', count: assistant?.personalizedAdvice?.length ?? 0,
            body: assistant?.personalizedAdvice?.map((item) => <article className="reply-candidate" key={`${item.category}-${item.title}`}>
              <Tag color={item.category === 'product_selection' ? 'warning' : 'processing'}>{item.title}</Tag>
              {item.productName ? <strong>{item.productName}</strong> : null}
              {item.productSku ? <Tag>{item.productSku}</Tag> : null}
              <p>{item.action}</p>
              <small>{item.rationale}</small>
              {item.evidence?.map((evidence) => <blockquote className="evidence-quote" key={`${evidence.sourceRef}-${evidence.quote}`}>
                <small>{evidence.label}</small><p>{evidence.quote}</p>
              </blockquote>)}
            </article>) },
        ]} />
      </> },
      { key: 'profile', label: '档案', children: <>
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
        <OrderFacts context={context} />
        <h3>工单 {tickets.length}</h3>
        <Button icon={<FileTextOutlined />} disabled={!id} onClick={() => setTicketDrawer(true)}>新建工单</Button>
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
    <QianniuTopbar title="客服工作台" stats={serviceMetricStats(metrics)} />
    <div className="reception-workspace">
      {!mobile && queue}
      <section className="reception-chat" aria-label="客服对话">
        <ChatHead item={current} switching={switching} onMode={(next) => void switchMode(next)}
          onTicket={() => setTicketDrawer(true)} onRefresh={() => id && void loadDetail(id)}
          leading={mobile && <Button icon={<MenuOutlined />} aria-label="会话列表" onClick={() => setQueueOpen(true)} />}
          trailing={compact && <Button icon={<ProfileOutlined />} aria-label="接待辅助" onClick={() => setPluginOpen(true)} />} />
        {id && <DeskProductCard conversationId={id} refreshKey={messages.length}
          onOpenOrder={() => { setPluginTab('profile'); if (compact) setPluginOpen(true) }} />}
        {(error || queueError) && <Alert type="error" title={error || queueError} showIcon
          action={<Button size="small" onClick={() => window.location.reload()}>刷新</Button>} />}
        <div className="anker-scroll chat-message-surface">{loading ? <Spin /> : <MessageList messages={messages} conversationId={id} viewRole="support"
          emotions={emotionsById} escalationMessageId={escalationId} buyerAlias={current?.buyerAlias} />}</div>
        {id && automatic ? <div className="anker-composer anker-hairline-top">
          <AiReceptionBar replying={aiReplying} switching={switching} onTakeOver={() => void switchMode('operator_assisted')} />
        </div> : <div className="anker-composer anker-hairline-top">
          {imageUpload.image?.error && <Alert type="error" showIcon title={imageUpload.image.error}
            closable={{ onClose: () => imageUpload.clear() }} />}
          <ChatImagePreview image={imageUpload.image} onRemove={() => imageUpload.clear()}
            disabled={sending || uploading} />
          <div className="composer-actions">
            <ChatImageButton upload={imageUpload.upload} disabled={!id || automatic || sending || uploading}
              uploading={uploading} />
            <span className="yt-tools-sep" /><Button type="text" className="yt-tool-ai" icon={<ThunderboltOutlined />} disabled={!id} loading={generating} onClick={() => { setPluginTab('assistant'); if (compact) setPluginOpen(true); void generate() }}>AI 建议</Button></div>
          {draftFindings.length > 0 && <div className="yt-draft-review" aria-label="发送前质检">
            {draftFindings.map((item) => <Tag key={`${item.kind}-${item.start}`}
              color={item.severity === 'high' ? 'error' : 'warning'} title={item.quote}>{item.label}</Tag>)}
          </div>}
          <Sender value={draft} components={{ input: ComposerInput }} placeholder="回复客户"
            onChange={(value) => id && drafts.set(id, 'support', value)} onSubmit={() => sendRef.current()}
            onPasteFile={(files) => { if (files[0]) void imageUpload.upload(files[0]) }}
            submitType="enter" disabled={!id || automatic || sending} loading={sending}
            suffix={(_, { components }) => <components.SendButton type="primary" shape="default"
              aria-label="发送" icon={<SendOutlined />} className="yt-send"
              disabled={!id || (!draft.trim() && !attachmentId) || automatic || sending || uploading}
              loading={sending}>发送</components.SendButton>} />
        </div>}
      </section>
      {!compact && <aside className="reception-plugin" aria-label="接待辅助信息">{plugin(true)}</aside>}
    </div>
    <Drawer title="会话" placement="left" size={300} open={queueOpen} onClose={() => setQueueOpen(false)}>{queue}</Drawer>
    <TicketDraftDrawer open={ticketDrawer} conversationId={id ?? null} buyerAlias={current?.buyerAlias} context={context}
      onClose={() => setTicketDrawer(false)}
      onCreated={() => { setTicketDrawer(false); if (id) void deskApi.tickets(id).then(setTickets) }} />
    <Drawer title="接待辅助" size={460} open={pluginOpen} onClose={() => setPluginOpen(false)}>{plugin(pluginOpen)}</Drawer>
  </div>
}
