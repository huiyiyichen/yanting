import {
  MenuOutlined, ProfileOutlined, ReloadOutlined,
  SendOutlined, ThunderboltOutlined, } from '@ant-design/icons'
import { Sender } from '@ant-design/x'
import { Alert, Button, Tooltip, Drawer, Spin, Tabs, Tag, message } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { deskApi, supportApi, type ConsumerServiceAssistantView, type ConsumerServiceContextView, type MessageView, type ReceptionSnapshot, type TicketView, type ServiceMemoryView, type HandoffSummaryView, type ConsumerProfileView, type ReceptionStatsView } from '../api/client'
import { MessageList } from '../components/MessageList'
import { ChatImageButton, ChatImagePreview, useChatImage } from '../components/ChatImageUpload'
import { PageHeader } from '../components/PageHeader'
import { Panorama } from '../features/panorama/Panorama'
import { makeSenderInput } from '../components/SenderParts'
import { useDraftStore } from '../features/conversation/draftStore'
import { newClientMessageKey } from '../features/conversation/messageDirection'

import { SupportRiskPanel } from '../features/service-desk/SupportRiskPanel'
import { escalationMessage, messageEmotions } from '../features/service-desk/messageEmotion'
import { AiReceptionBar, ChatHead } from '../features/service-desk/ChatHead'
import { ReceptionQueue } from '../features/service-desk/ReceptionQueue'
import { DeskProductCard } from '../features/service-desk/DeskProductCard'
import { ArchivePanel } from '../features/service-desk/ArchivePanel'
import { PersonaCard } from '../features/service-desk/PersonaCard'
import { shouldHoldSend, useDraftReview } from '../features/service-desk/draftReview'
import { serviceMetricStats } from '../features/service-desk/serviceMetrics'
import { TicketDraftDrawer } from '../features/service-desk/TicketDraftDrawer'
import { ReplyCard } from '../features/service-desk/ReplyCard'
import { EvidenceFolds, HandoffSummary, IntentRow, NextSteps } from '../features/service-desk/AssistBlocks'
import { useIsNarrow } from '../hooks/useMediaQuery'
import { ServiceJourney } from '../features/service-desk/ServiceJourney'
import { visibleInterval } from '../hooks/visibleInterval'

const ComposerInput = makeSenderInput('客服回复输入框')
const intentLabels: Record<string, string> = {
  product_question: '商品咨询', order_status: '订单查询', logistics: '物流查询',
  refund: '退款', return: '退货', replacement: '补发换货', adverse_reaction: '使用不适',
  complaint: '投诉', other: '其他诉求', unknown: '待明确',
}

const VIEW_KEY = 'yt.support.view'

export function SupportWorkbench() {
  const [params, setParams] = useSearchParams()
  const routeId = params.get('conversation')
  const panoramaView = params.get('view') === 'panorama'
  useEffect(() => {
    if (!params.get('view') && !routeId && localStorage.getItem(VIEW_KEY) === 'panorama') setParams({ view: 'panorama' }, { replace: true })
  }, [params, routeId, setParams])
  const switchView = (next: 'desk' | 'panorama') => {
    localStorage.setItem(VIEW_KEY, next)
    setParams(next === 'panorama' ? { view: 'panorama' } : id ? { conversation: id } : {})
  }
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
    const stop = visibleInterval(read, 15000)
    return () => { cancelled = true; stop() }
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
  const handoffGenerated = useRef(new Set<string>())
  const [handoff, setHandoff] = useState<HandoffSummaryView | null>(null)
  const [summarizing, setSummarizing] = useState(false)
  sendRef.current = () => { void send() }

  const loadDetail = useCallback(async (target: string) => {
    const request = ++detailRequest.current
    const analysisVersion = assistantRequest.current
    try {
      const [rows, facts, cached, work, remembered, persona, handoff] = await Promise.all([
        supportApi.receptionMessages(target), supportApi.serviceContext(target),
        supportApi.assistant(target), deskApi.tickets(target), supportApi.memory(target),
        supportApi.profile(target).catch(() => null), supportApi.handoffSummary(target).catch(() => null),
      ])
      if (active.current !== target || request !== detailRequest.current) return
      setMessages(rows); setContext(facts); setTickets(work); setMemory(remembered); setProfile(persona); setHandoff(handoff); setError('')
      if (analysisVersion === assistantRequest.current) setAssistant(cached)
      await supportApi.markSeen(target, rows.at(-1)?.messageRevision ?? 0)
    } catch (err) {
      if (active.current === target) setError((err as Error).message)
    } finally {
      if (active.current === target) setLoading(false)
    }
  }, [])

  useEffect(() => {
    setMessages([]); setContext(null); setAssistant(null); setTickets([]); setMemory(null); setProfile(null); setHandoff(null); setAiError('')
    if (id) { setLoading(true); void loadDetail(id) }
  }, [id, loadDetail])

  // 转人工（系统判定或客户要求）后由交接摘要 Agent 单独生成一次（不再跑整条起草流程）；同一次转人工只生成一次
  const handoffKey = current?.serviceMode === 'operator_assisted' && current.handoffReason ? `${current.conversationId}:${current.modeRevision}` : ''
  useEffect(() => {
    if (!id || !handoffKey || loading || context?.conversationId !== id || handoffGenerated.current.has(handoffKey)) return
    handoffGenerated.current.add(handoffKey)
    if (handoff && !handoff.stale && handoff.source === 'model') return
    const target = id
    setSummarizing(true)
    supportApi.generateHandoffSummary(target)
      .then((view) => { if (active.current === target) setHandoff(view) })
      .catch(() => undefined)
      .finally(() => { if (active.current === target) setSummarizing(false) })
  }, [id, handoffKey, loading, context])

  // 用户反馈 6：打开会话或客户来新消息时自动生成回复建议与交接摘要（输入未变时后端直接复用缓存，不重复调用模型）
  const lastCustomerKey = (() => {
    const last = [...messages].reverse().find((row) => row.senderRole === 'customer')
    return last ? `${id}:${last.messageId ?? ''}` : ''
  })()
  const autoGenerated = useRef(new Set<string>())
  useEffect(() => {
    if (!id || !lastCustomerKey || automatic || loading || generating || context?.conversationId !== id) return
    if (assistant && !assistant.stale) return
    if (autoGenerated.current.has(lastCustomerKey)) return
    autoGenerated.current.add(lastCustomerKey)
    void generate(id)
  }, [id, lastCustomerKey, automatic, loading, context, assistant])

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
          // 保留 view 等其他参数：全景视图下自动选中首个会话不能把页面切回工作台
          setParams((prev) => { const nextParams = new URLSearchParams(prev); nextParams.set('conversation', firstId); return nextParams }, { replace: true })
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
    const stop = visibleInterval(() => void sync(), 1500)
    window.addEventListener('focus', sync)
    return () => { disposed = true; stop(); window.removeEventListener('focus', sync) }
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
      const next = await supportApi.reception()
      setSnapshot(next)
      const switched = next.items.find((item) => item.conversationId === origin)
      if (mode === 'operator_assisted' && switched) handoffGenerated.current.add(`${origin}:${switched.modeRevision}`)
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
  const openConversation = useCallback((conversationId: string) => {
    setParams({ conversation: conversationId }); setQueueOpen(false)
  }, [setParams])
  const queue = <ReceptionQueue items={snapshot?.items ?? []} activeId={id} onOpen={openConversation} />

  const riskRefreshKey = [
    current?.messageRevision ?? 0, current?.modeRevision ?? 0,
    current?.activeRiskTypes?.join(',') ?? '', current?.reviewRiskTypes?.join(',') ?? '',
  ].join('|')
  const refreshAfterIntervention = async (target: string) => {
    if (active.current !== target) return
    setSnapshot(await supportApi.reception())
    await loadDetail(target)
    if (active.current === target) await generate(target)
  }
  const plugin = (visible: boolean) => <div className="desk-plugin-inner">
    <Tabs size="small" className="yt-ptabs" activeKey={pluginTab} onChange={setPluginTab}
      tabBarExtraContent={{
        left: <span className="yt-pbrand"><span className={`yt-wave${generating ? ' is-busy' : ''}`} aria-hidden="true"><i /><i /><i /><i /><i /></span>颜听</span>,
        right: <Tooltip title="刷新数据"><Button type="text" className="yt-pbar-btn"
          aria-label="刷新数据" icon={<ReloadOutlined />} disabled={!id}
          onClick={() => { if (id) void loadDetail(id) }} /></Tooltip>,
      }} items={[
      { key: 'assistant', label: '辅助', children: <>
        {profile?.memory && profile.conversationId === id ? <PersonaCard profile={profile} /> : null}
        {aiError && <Alert type="error" title={aiError} showIcon />}
        {assistant && !assistant.stale && assistant.replySuggestions.length ? <>
          {assistant.verificationStatus === 'partial' && <Tag color="warning">
            已移除 {Number(assistant.modelUsage?.segmentsDropped ?? 0)} 段
          </Tag>}
          <ReplyCard key={`${id}-${assistant.inputHash}`}
            suggestions={assistant.replySuggestions} sources={assistant.groundingSources ?? []} automatic={automatic} generating={generating}
            adoptable={['verified', 'partial', 'needs_review'].includes(assistant.verificationStatus ?? '')}
            onAdopt={(style, body, edited) => void adopt(style, body, edited ? 'adopt_edited' : 'adopt')}
            onIgnore={(style) => void adopt(style, '', 'ignore')}
            onRegenerate={(style) => void generate(id, style)} onRewrite={rewrite} />
        </> : <section className="service-section yt-card yt-reply-empty" aria-label="回复建议">
          <h3>回复建议<span className="r">{generating ? '生成中' : <Button size="small" type="link" disabled={!id}
            onClick={() => void generate()}>{assistant?.stale ? '重新生成' : '生成'}</Button>}</span></h3>
          {generating && stages.length > 0 && <ol className="yt-stages" aria-label="生成进度">
            {stages.map((item) => <li key={item.name} className={`is-${item.status}`}>{item.name}</li>)}
          </ol>}
        </section>}
        <HandoffSummary summary={handoff && !handoff.stale ? handoff.summary : assistant && !assistant.stale ? assistant.serviceSummary : null}
          state={summarizing || (generating && !handoff) ? '生成中' : handoff && !handoff.stale ? null : assistant?.stale ? '待更新' : assistant ? null : '待生成'} />
        {assistant && !assistant.stale ? <IntentRow primary={intentLabels[assistant.intent ?? 'unknown']}
          items={profile?.conversationId === id ? (profile?.memory?.pending ?? []).map((item) => item.text) : []}
          missing={assistant.missingInformation} /> : null}
        {id ? <SupportRiskPanel key={id} conversationId={id}
          enabled={visible && pluginTab === 'assistant'} refreshKey={riskRefreshKey}
          serviceMode={current?.serviceMode} onIntervened={refreshAfterIntervention} /> : null}
        {assistant && !assistant.stale ? <NextSteps scope={`${id}:${assistant.inputHash}`} steps={assistant.nextSteps} /> : null}
        <EvidenceFolds folds={[
          { key: 'knowledge', label: '知识依据', icon: 'knowledge', count: assistant?.knowledgeEvidence?.length ?? 0,
            body: assistant?.knowledgeEvidence?.length ? assistant.knowledgeEvidence.map((item, i) => <div className="evidence-quote" key={i}>
              <strong>{String(item.document_title ?? '')}</strong><p>{String(item.quoted_excerpt ?? '')}</p>
            </div>) : <p className="yt-empty">{assistant?.knowledgeStatus === 'failed' ? '检索失败' : '依据不足'}</p> },
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
      { key: 'profile', label: '档案', children: <ArchivePanel context={context} memory={memory} tickets={tickets}
        onOpenTicket={(ticketId) => navigate(`/platform/work-orders?ticket=${ticketId}`)} onNewTicket={() => setTicketDrawer(true)} /> },
      { key: 'history', label: '轨迹', children: <ServiceJourney context={context} profile={profile} /> },
    ]} />
  </div>
  return <div className="desk-workbench">
    {holder}
    <PageHeader title={<span className="yt-view-seg" role="radiogroup" aria-label="接待视图">
      {([['desk', '工作台'], ['panorama', '全景']] as const).map(([key, label]) => <button key={key} type="button" role="radio"
        aria-checked={(key === 'panorama') === panoramaView} className={(key === 'panorama') === panoramaView ? 'on' : undefined}
        onClick={() => switchView(key)}>{label}</button>)}
    </span>} stats={serviceMetricStats(metrics)} />
    {panoramaView ? <Panorama onOpen={(cid) => { localStorage.setItem(VIEW_KEY, 'desk'); setParams({ conversation: cid }) }} /> : <>
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
        <div className="yt-scroll chat-message-surface">{loading ? <Spin /> : <MessageList messages={messages} conversationId={id} viewRole="support"
          emotions={emotionsById} escalationMessageId={escalationId} buyerAlias={current?.buyerAlias} />}</div>
        {id && automatic ? <div className="yt-composer yt-hairline-top">
          <AiReceptionBar replying={aiReplying} switching={switching} onTakeOver={() => void switchMode('operator_assisted')} />
        </div> : <div className="yt-composer yt-hairline-top">
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
    </>}
    <Drawer title="会话" placement="left" size={300} open={queueOpen} onClose={() => setQueueOpen(false)}>{queue}</Drawer>
    <TicketDraftDrawer open={ticketDrawer} conversationId={id ?? null} buyerAlias={current?.buyerAlias} context={context}
      onClose={() => setTicketDrawer(false)}
      onCreated={() => { setTicketDrawer(false); if (id) void deskApi.tickets(id).then(setTickets) }} />
    <Drawer title="接待辅助" size={460} open={pluginOpen} onClose={() => setPluginOpen(false)}>{plugin(pluginOpen)}</Drawer>
  </div>
}
