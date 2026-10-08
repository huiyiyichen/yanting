import { CheckOutlined, CloseOutlined, EyeOutlined, FileTextOutlined, MessageOutlined, MoreOutlined, PlayCircleOutlined, ReloadOutlined, SearchOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { Alert, Button, Collapse, Drawer, Dropdown, Empty, Input, Modal, Select, Space, Table, Tabs, Tag, Timeline, message } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, deskApi, supportApi, type ReceptionItem, type RiskIncidentDetailView, type RiskIncidentView } from '../api/client'
import { QianniuTopbar } from '../components/QianniuTopbar'
import { OrderFacts, ServiceTimeline, TicketStatus, dateLabel, optionsOf } from '../features/service-desk/shared'
import { serviceRiskTypeLabels } from '../contracts/enums'
import { emotionStatus, followupDeadlines, primaryConversation, signalAttention } from '../features/service-desk/riskPresentation'
import { EmotionArc } from '../features/service-desk/EmotionArc'

const actionLabels = { resolved: '复核关闭', ignored: '忽略风险', reopen: '重新介入' }
const actionResults = {
  resolved: ['已核对，风险已消退', '消费者确认问题已解决', '已核实无需继续跟进'],
  ignored: ['重复预警', '无需跟进', '记录不适用'],
  reopen: ['需重新核对', '出现新的待处理事项'],
}
const levelLabels: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险', unknown: '未知' }
const emotionLabels: Record<string, string> = { calm: '平稳', dissatisfied: '不满', angry: '激烈', unknown: '未知' }
const serviceStateLabels: Record<string, string> = { live: '服务中', closed: '服务已结束', historical: '历史记录' }
const currentActionLabels: Record<string, string> = { intervene: '待处理', review: '待复核', record_only: '历史记录', none: '已归档' }
type Signal = RiskIncidentView['signals'][number]
type RiskAction = { status: keyof typeof actionLabels; incidentId: string; expectedVersion: string }

function signalState(signal: Signal, incident: RiskIncidentView) {
  const judgment = incident.judgments?.find((item) => item.alertId === signal.alertId)
  if (judgment?.verdict === 'false_positive' && !judgment.stale) return '已标误报'
  return { active: '当前触发', review: '待复核', historical: '历史信号', closed: '已关闭' }[signalAttention(signal)]
}

function analysisError(error: unknown) {
  if (error instanceof ApiError) {
    return ({
      model_output_invalid: '分析结果暂不可用，请重试',
      provider_timeout: '分析超时，请重试',
      provider_not_configured: '模型未配置',
      provider_request_failed: '模型连接失败，请重试',
    } as Record<string, string>)[error.code ?? ''] ?? error.message
  }
  return error instanceof Error ? error.message : '分析失败，请重试'
}

export function RiskDashboardPage() {
  const [rows, setRows] = useState<RiskIncidentView[]>([])
  const [receptionItems, setReceptionItems] = useState<ReceptionItem[]>([])
  const [selected, setSelected] = useState<RiskIncidentDetailView | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [mode, setMode] = useState('initial')
  const [type, setType] = useState<string>()
  const [level, setLevel] = useState<string>()
  const [error, setError] = useState('')
  const [runtimeWarning, setRuntimeWarning] = useState(false)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [analyzingId, setAnalyzingId] = useState<string | null>(null)
  const [analysisErrors, setAnalysisErrors] = useState<Record<string, string>>({})
  const [inspectionId, setInspectionId] = useState<string>()
  const [action, setAction] = useState<RiskAction | null>(null)
  const [result, setResult] = useState<string>()
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [toast, holder] = message.useMessage()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requestedConversation = searchParams.get('conversation')
  const requestedType = searchParams.get('type')
  const requestedIncident = searchParams.get('incident')
  const handledLink = useRef('')
  const detailRequest = useRef(0)
  const listRequest = useRef(0)
  const selectedListRow = rows.find((row) => row.incidentId === selectedId)
  const selectedVersion = selectedListRow?.version
  const selectedLatestMessage = selectedListRow?.latestMessage
  const load = useCallback(async (silent = false) => {
    const request = ++listRequest.current
    if (!silent) setLoading(true)
    try {
      const [data, reception] = await Promise.all([deskApi.risks(), supportApi.reception()])
      if (request === listRequest.current) {
        setRows(data)
        setReceptionItems(reception.items)
        setMode((current) => current === 'initial'
          ? data.some((row) => row.currentAction === 'record_only') ? 'historical' : 'active'
          : current)
        setRuntimeWarning(data.some((row) => !row.serviceState || !row.currentAction))
        setError('')
      }
      return data
    } catch (err) { if (request === listRequest.current) setError((err as Error).message) }
    finally { if (request === listRequest.current) setLoading(false) }
  }, [])
  useEffect(() => {
    void load()
    const sync = () => { if (!document.hidden) void load(true) }
    const timer = window.setInterval(sync, 10000)
    window.addEventListener('focus', sync)
    return () => { window.clearInterval(timer); window.removeEventListener('focus', sync); listRequest.current++ }
  }, [load])
  useEffect(() => {
    const request = ++detailRequest.current
    setSelected((old) => old?.incident.incidentId === selectedId ? old : null)
    if (selectedId) void deskApi.risk(selectedId).then((data) => {
      if (request === detailRequest.current) setSelected(data)
    }).catch((err: Error) => { if (request === detailRequest.current) setError(err.message) })
    return () => { detailRequest.current++ }
  }, [selectedId, selectedVersion, selectedLatestMessage])
  useEffect(() => {
    const key = `${requestedConversation ?? ''}:${requestedType ?? ''}:${requestedIncident ?? ''}`
    if ((!requestedConversation && !requestedIncident) || handledLink.current === key || !rows.length) return
    const matching = rows.filter((item) => item.conversationIds.includes(requestedConversation ?? ''))
    const row = rows.find((item) => item.incidentId === requestedIncident)
      ?? matching.find((item) => item.signals.some((signal) => signal.riskType === requestedType)) ?? matching[0]
    if (row) {
      handledLink.current = key
      setSelectedId(row.incidentId)
      setMode(row.currentAction === 'record_only' ? 'historical' : row.currentAction === 'intervene'
        ? 'active' : row.currentAction === 'review' ? 'review' : 'closed')
    }
  }, [requestedConversation, requestedType, requestedIncident, rows])
  const openConversation = (id: string) => navigate(`/support?conversation=${encodeURIComponent(id)}`)
  const closeDetail = () => { setSelectedId(null); setAction(null) }
  const refreshDetail = async (incidentId: string, request = detailRequest.current) => {
    const detail = await deskApi.risk(incidentId)
    if (request === detailRequest.current) setSelected(detail)
  }
  const beginAction = (status: RiskAction['status']) => {
    if (!selected) return
    setAction({ status, incidentId: selected.incident.incidentId, expectedVersion: selected.incident.version })
    setResult(undefined)
    setNote('')
  }
  const scan = async () => {
    setScanning(true)
    try { await deskApi.scan(); await load(); void toast.success('扫描完成') }
    catch (err) { setError((err as Error).message) }
    finally { setScanning(false) }
  }
  const analyze = async (conversationId: string) => {
    if (analyzingId) return
    const request = detailRequest.current
    const incidentId = selectedId
    setAnalyzingId(conversationId)
    setAnalysisErrors((old) => { const next = { ...old }; delete next[conversationId]; return next })
    try {
      const assessment = await deskApi.analyzeBreakpoints(conversationId)
      if (incidentId) await refreshDetail(incidentId, request)
      await load(true)
      void toast.success(assessment.findings?.length ? '分析已保存' : '未发现服务断点')
    } catch (err) { setAnalysisErrors((old) => ({ ...old, [conversationId]: analysisError(err) })) }
    finally { setAnalyzingId(null) }
  }
  const takeOver = async () => {
    if (!selected || saving) return
    const incident = selected.incident
    const conversationId = primaryConversation(incident)
    if (!conversationId) return
    setSaving(true)
    try {
      await deskApi.interveneRisk(incident.incidentId, conversationId, incident.version)
      openConversation(conversationId)
    } catch (err) {
      void toast.error((err as Error).message)
      if (err instanceof ApiError && err.isConflict) await refreshDetail(incident.incidentId)
    } finally { setSaving(false) }
  }
  const feedback = async (signal: Signal, restore: boolean) => {
    if (!selected || saving) return
    const request = detailRequest.current
    const incident = selected.incident
    setSaving(true)
    try {
      const detail = await deskApi.judgeRisk(incident.incidentId, signal.alertId, {
        verdict: restore ? 'confirmed' : 'false_positive',
        note: restore ? '客服恢复预警' : '客服确认误报',
        expectedVersion: incident.version,
        expectedJudgmentId: incident.judgments?.find((item) => item.alertId === signal.alertId)?.judgmentId ?? null,
      })
      if (request === detailRequest.current) setSelected(detail)
      await load(true)
      void toast.success(restore ? '预警已恢复' : '已标记误报')
    } catch (err) {
      void toast.error((err as Error).message)
      if (err instanceof ApiError && err.isConflict) await refreshDetail(incident.incidentId, request)
    } finally { setSaving(false) }
  }
  const handle = async () => {
    if (!action || !result || saving) return
    const nextAction = action
    const request = detailRequest.current
    setSaving(true)
    try {
      const detail = await deskApi.updateRisk(nextAction.incidentId, nextAction.status,
        [result, note.trim()].filter(Boolean).join('；'), nextAction.expectedVersion)
      if (request === detailRequest.current) { setSelected(detail); setAction(null) }
      await load(true)
      void toast.success(`${actionLabels[nextAction.status]}已记录`)
    } catch (err) {
      void toast.error((err as Error).message)
      if (err instanceof ApiError && err.isConflict) {
        setAction(null)
        await refreshDetail(nextAction.incidentId, request)
      }
    } finally { setSaving(false) }
  }
  const active = rows.filter((row) => row.currentAction === 'intervene')
  const review = rows.filter((row) => row.currentAction === 'review')
  const historical = rows.filter((row) => row.currentAction === 'record_only')
  const lowRisk = rows.filter((row) => row.riskLevel === 'low')
  const safeCustomers = receptionItems.filter((item) =>
    item.dataSource === 'live' && !item.activeRiskTypes?.length && !item.reviewRiskTypes?.length)
  const filtered = rows.filter((row) =>
    (mode === 'all' || (mode === 'safe') || (mode === 'active' ? row.currentAction === 'intervene'
      : mode === 'review' ? row.currentAction === 'review' : mode === 'historical'
        ? row.currentAction === 'record_only' : row.attentionState === 'closed'))
    && (!level || row.riskLevel === level)
    && (!type || row.signals.some((signal) => signal.riskType === type && (mode !== 'active' || signalAttention(signal) === 'active')))
    && `${row.buyerAlias} ${row.orderIds.join(' ')} ${row.latestMessage}`.includes(query))
  const safeFiltered = safeCustomers.filter((item) =>
    `${item.buyerAlias} ${item.conversationId} ${item.preview}`.includes(query))
  const incident = selected?.incident
  const primaryId = incident && primaryConversation(incident)
  const assessments = selected?.serviceBreakpointAssessments ?? []
  const inspection = assessments.find((item) => item.conversationId === inspectionId)
    ?? assessments.find((item) => item.conversationId === requestedConversation)
    ?? assessments.find((item) => item.conversationId === primaryId) ?? assessments[0]
  const openTicket = selected?.tickets.find((ticket) => ticket.status !== 'resolved')
  const signalGroups = new Map<string, Signal[]>()
  for (const signal of incident?.signals ?? []) {
    const group = signalGroups.get(signal.riskType) ?? []
    group.push(signal)
    signalGroups.set(signal.riskType, group)
  }
  const evidenceQuote = (evidence: RiskIncidentDetailView['evidence'][number], fallbackId?: string) => {
    const conversationId = evidence.conversationId ?? (evidence.kind.includes('message') || evidence.kind === 'history_context'
      ? (selected?.incident.conversationIds.includes(evidence.label) || selected?.contactHistory?.some((point) => point.label === evidence.label)
        ? evidence.label : fallbackId) : undefined)
    return <blockquote className="evidence-quote" key={evidence.ref}>
      <div className="section-title-row"><span>{dateLabel(evidence.occurredAt)} · {evidence.label}</span>
        {conversationId && <Button size="small" type="text" icon={<MessageOutlined />} onClick={() => openConversation(conversationId)}>打开会话</Button>}</div>
      <p>{evidence.body}</p>
    </blockquote>
  }
  return <div className="desk-workbench">{holder}
    <QianniuTopbar title="风险预警" stats={mode === 'historical' ? [
      { label: '官方事件', value: historical.length },
      { label: '高风险', value: historical.filter((row) => row.riskLevel === 'high').length, warning: true },
      { label: '情绪升级', value: historical.filter((row) => row.signals.some((signal) => signal.riskType === 'emotion_escalation')).length },
      { label: '重复进线', value: historical.filter((row) => row.signals.some((signal) => signal.riskType === 'repeated_contact')).length },
    ] : mode === 'safe' ? [
      { label: '低风险', value: lowRisk.length },
      { label: '当前无风险', value: safeCustomers.length },
      { label: '待复核', value: review.length },
      { label: '官方记录', value: historical.length },
    ] : [
      { label: '待处理', value: runtimeWarning ? '未加载' : active.length, warning: true },
      { label: '高风险', value: active.filter((row) => row.riskLevel === 'high').length, warning: true },
      { label: '情绪加剧', value: active.filter((row) => row.emotionTrend === 'rising').length, warning: true },
      { label: '待复核', value: review.length },
    ]} actions={<Space><Button icon={<ReloadOutlined />} aria-label="刷新风险" loading={loading} onClick={() => void load()} />
      <Button icon={<PlayCircleOutlined />} loading={scanning} onClick={() => void scan()}>扫描异常</Button></Space>} />
    <div className="desk-page-body">
      {error && <Alert type="error" title={error} showIcon />}
      {runtimeWarning && <Alert type="warning" title="风险接口版本过旧，请更新后端" showIcon />}
      <Tabs activeKey={mode} onChange={setMode} items={[
        { key: 'historical', label: `官方记录 ${historical.length}` },
        { key: 'safe', label: `低风险 / 无风险 ${lowRisk.length + safeCustomers.length}` },
        { key: 'active', label: `待处理 ${active.length}` }, { key: 'review', label: `待复核 ${review.length}` },
        { key: 'closed', label: '已关闭' }, { key: 'all', label: '全部事件' },
      ]} />
      <div className="desk-filterbar">
        <Input prefix={<SearchOutlined />} aria-label="搜索风险" placeholder="客户、订单、最新消息" allowClear value={query} onChange={(e) => setQuery(e.target.value)} />
        <Select aria-label="风险等级" placeholder="风险等级" allowClear value={level} onChange={setLevel} options={optionsOf(levelLabels)} />
        <Select aria-label="风险类型" placeholder="风险类型" allowClear value={type} onChange={setType} options={optionsOf(serviceRiskTypeLabels)} />
      </div>
      {mode === 'safe' ? <Table<ReceptionItem> rowKey="conversationId" size="small" dataSource={safeFiltered} loading={loading}
        pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: '当前没有无风险客户' }}
        columns={[
          { title: '消费者', width: 200, render: (_, item) => <div className="table-cell-stack"><strong>{item.buyerAlias}</strong><span>服务中</span></div> },
          { title: '风险等级', width: 140, render: () => <Tag color="success">无风险</Tag> },
          { title: '当前情绪', width: 140, render: (_, item) => <Tag color={item.currentEmotion === 'calm' ? 'success' : 'warning'}>
            {item.currentEmotion === 'calm' ? '平稳' : item.currentEmotion === 'dissatisfied' ? '不满' : '未知'}
          </Tag> },
          { title: '最新消费者消息', render: (_, item) => <div className="table-cell-stack"><div className="table-excerpt">{item.preview || '暂无消息'}</div><span>{dateLabel(item.updatedAt)}</span></div> },
          { title: '操作', width: 100, render: (_, item) => <Button aria-label={`打开会话 ${item.buyerAlias}`} size="small" icon={<MessageOutlined />} onClick={() => openConversation(item.conversationId)} /> },
        ]} /> : <Table<RiskIncidentView> rowKey="incidentId" size="small" dataSource={filtered} loading={loading} scroll={{ x: 1050 }} pagination={{ pageSize: 10, showSizeChanger: false }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={runtimeWarning ? '当前预警未加载' : '暂无风险事件'} /> }}
        columns={[
          { title: '等级 / 状态', width: 125, render: (_, row) => <div className="table-cell-stack">
            <Tag color={row.riskLevel === 'high' ? 'error' : row.riskLevel === 'medium' ? 'warning' : 'default'}>{levelLabels[row.riskLevel]}</Tag>
            <span>{row.currentAction === 'intervene' && row.riskStatus === 'in_progress' ? '处理中' : currentActionLabels[row.currentAction]}</span>
          </div> },
          { title: '消费者', width: 180, render: (_, row) => <div className="table-cell-stack"><strong>{row.buyerAlias}</strong><span>{serviceStateLabels[row.serviceState]}</span></div> },
          { title: '风险 / 原因', width: 290, render: (_, row) => {
            const signals = row.signals.filter((signal) => mode !== 'active' || signalAttention(signal) === 'active')
            const unique = [...new Map(signals.map((signal) => [`${signal.riskType}:${signalAttention(signal)}`, signal])).values()]
            return <div className="table-cell-stack"><Space size={[0, 4]} wrap>{unique.map((signal) => <Tag
              color={signalAttention(signal) === 'active' ? 'warning' : 'default'} key={`${signal.riskType}:${signalAttention(signal)}`}>
              {serviceRiskTypeLabels[signal.riskType]}
            </Tag>)}{row.historicalSensitivity > 0 && <Tag color="processing">历史敏感 {row.historicalSensitivity}/3</Tag>}</Space><div className="table-excerpt">{(signals.find((signal) => signalAttention(signal) === 'active')
              ?? signals.find((signal) => signalAttention(signal) === 'review') ?? signals[0])?.triggerSummary}</div></div>
          } },
          { title: mode === 'historical' ? '结束时情绪' : '当前情绪', width: 125, render: (_, row) => <Tag color={row.currentEmotion === 'angry' ? 'error' : row.currentEmotion === 'dissatisfied' ? 'warning' : row.currentEmotion === 'calm' ? 'success' : 'default'}>{emotionStatus(row)}</Tag> },
          { title: '最新消费者消息', width: 280, render: (_, row) => <div className="table-cell-stack"><div className="table-excerpt">{row.latestMessage || '暂无消息'}</div><span>{dateLabel(row.latestCustomerAt)}</span></div> },
          { title: '操作', width: 155, render: (_, row) => <Space>
            <Button data-testid={`risk-open-${row.incidentId}`} size="small" icon={<EyeOutlined />} onClick={() => setSelectedId(row.incidentId)}>详情</Button>
            <Button aria-label={`打开会话 ${row.buyerAlias}`} title="打开会话" size="small" icon={<MessageOutlined />} disabled={!primaryConversation(row)}
              onClick={() => { const id = primaryConversation(row); if (id) openConversation(id) }} />
          </Space> },
        ]} />}
    </div>
    <Drawer title="风险详情" size={640} open={Boolean(selectedId)} onClose={closeDetail}>
      {selected && incident && <>
        <div className="section-title-row"><h2>{incident.buyerAlias}</h2><Space wrap>
          <Tag color={incident.riskLevel === 'high' ? 'error' : incident.riskLevel === 'medium' ? 'warning' : 'default'}>{levelLabels[incident.riskLevel]}</Tag>
          <Tag>{serviceStateLabels[incident.serviceState]}</Tag>
          <Tag color={incident.currentEmotion === 'angry' ? 'error' : incident.currentEmotion === 'dissatisfied' ? 'warning' : incident.currentEmotion === 'calm' ? 'success' : 'default'}>{emotionStatus(incident)}</Tag>
          {incident.historicalSensitivity > 0 && <Tag color="processing">历史敏感度 {incident.historicalSensitivity}/3</Tag>}
        </Space></div>
        <div className="risk-actions">
          <Button icon={<MessageOutlined />} disabled={!primaryId} onClick={() => primaryId && openConversation(primaryId)}>打开当前会话</Button>
          {incident.currentAction === 'intervene' && incident.serviceState === 'live' &&
            <Button type="primary" icon={<PlayCircleOutlined />} loading={saving} disabled={!primaryId} onClick={() => void takeOver()}>接管并回复</Button>}
          {incident.currentAction === 'intervene' && incident.serviceState !== 'live' && openTicket &&
            <Button type="primary" onClick={() => navigate(`/platform/work-orders?ticket=${encodeURIComponent(openTicket.ticketId)}`)}>跟进工单</Button>}
          <Button icon={<CheckOutlined />} disabled={!(incident.riskStatus === 'in_progress'
            || (incident.riskStatus === 'pending' && incident.attentionState === 'review' && incident.currentAction === 'review'))}
            onClick={() => beginAction('resolved')}>复核关闭</Button>
          <Dropdown menu={{ items: [
            { key: 'ignored', label: '忽略风险', icon: <CloseOutlined />, disabled: !['pending', 'in_progress'].includes(incident.riskStatus) },
            { key: 'reopen', label: '重新介入', icon: <ReloadOutlined />, disabled: !['resolved', 'ignored'].includes(incident.riskStatus) },
          ], onClick: ({ key }) => beginAction(key as RiskAction['status']) }}>
            <Button aria-label="更多处置" title="更多处置" icon={<MoreOutlined />} />
          </Dropdown>
        </div>
        <Tabs items={[
          { key: 'evidence', label: '风险依据', children: <>
            {[...signalGroups.values()].map((group) => {
              const signal = group.find((item) => signalAttention(item) === 'active') ?? group[0]
              const evidence = [...new Map(group.flatMap((item) => (item.evidenceRefs ?? []).flatMap((ref) => {
                const point = selected.evidence.find((entry) => entry.ref === ref)
                return point ? [[ref, { point, conversationId: item.conversationId }] as const] : []
              }))).values()]
              const targets = group.filter((item) => !['resolved', 'ignored'].includes(item.riskStatus))
              return <section key={signal.riskType} className="service-section">
              <div className="section-title-row"><h3>{serviceRiskTypeLabels[signal.riskType]}</h3><Space>
                <Tag color={signalAttention(signal) === 'active' ? 'error' : 'default'}>{signalState(signal, incident)}</Tag>
                {targets.length > 0 && <Dropdown menu={{ items: targets.map((item) => ({
                  key: item.alertId, label: `${signalState(item, incident) === '已标误报' ? '恢复预警' : '标记误报'}${targets.length > 1 ? ` · ${item.conversationId}` : ''}`,
                })), onClick: ({ key }) => {
                  const target = targets.find((item) => item.alertId === key)
                  if (!target) return
                  const restore = signalState(target, incident) === '已标误报'
                  Modal.confirm({ title: restore ? '恢复这条预警？' : '将这条预警标记为误报？',
                    okText: '确认', cancelText: '取消', onOk: () => feedback(target, restore) })
                } }}><Button size="small" type="text" icon={<MoreOutlined />} aria-label={`信号操作 ${signal.alertId}`} disabled={saving} /></Dropdown>}
              </Space></div>
              <p>{signal.triggerSummary}</p>
              {signalAttention(signal) === 'active' && <p className="next-action">{signal.recommendedAction}</p>}
              {[...new Map(group.flatMap((item) => followupDeadlines(item.conditions)).map((deadline) => [deadline.ticketId, deadline])).values()].map((deadline) => <Tag key={deadline.ticketId}>
                {deadline.ticketId} · 截止 {dateLabel(deadline.dueAt)}
              </Tag>)}
              {evidence.map(({ point, conversationId }) => evidenceQuote(point, conversationId))}
              {!evidence.some(({ point }) => point.kind.includes('message')) && <Button size="small" icon={<MessageOutlined />} disabled={!signal.conversationId}
                onClick={() => openConversation(signal.conversationId)}>打开相关会话</Button>}
            </section> })}
            {inspection && <Collapse ghost items={[(() => {
              const item = inspection
              const findings = item.findings ?? []
              const status = item.stale ? '待更新分析' : item.analyzed
                ? findings.length ? '已分析' : '未发现服务断点' : '未分析'
              return {
                key: 'inspection',
                label: '服务排查',
                children: <Space orientation="vertical" style={{ width: '100%' }}>
                  {assessments.length > 1 && <Select aria-label="排查会话" value={item.conversationId}
                    style={{ width: '100%' }} onChange={setInspectionId}
                    options={assessments.map((candidate) => ({
                      value: candidate.conversationId, label: candidate.conversationId,
                    }))} />}
                  <Space wrap>
                    <Button aria-label={assessments.length === 1 ? '分析服务断点' : `分析服务断点 ${item.conversationId}`} icon={<ThunderboltOutlined />}
                      loading={analyzingId === item.conversationId}
                      disabled={Boolean(analyzingId) && analyzingId !== item.conversationId}
                      onClick={() => void analyze(item.conversationId)}>分析服务断点</Button>
                    <Button size="small" icon={<MessageOutlined />} aria-label={`打开会话 ${item.conversationId}`}
                      onClick={() => openConversation(item.conversationId)}>打开会话</Button>
                    <Tag>{status}</Tag>
                  </Space>
                  {analysisErrors[item.conversationId] && <Alert type="error" showIcon title={analysisErrors[item.conversationId]} />}
                  {findings.map((finding, index) => <section className="service-section" key={`${finding.kind}-${index}`}>
                    <h3>{finding.topic} · {finding.kindLabel}</h3><p>{finding.reason}</p>
                    {finding.promiseDueAt && <Tag color="warning">承诺截止 {dateLabel(finding.promiseDueAt)}</Tag>}
                    {finding.evidence.map((evidence) => evidenceQuote({
                      ref: evidence.sourceRef, body: evidence.quote, label: evidence.label,
                      kind: evidence.kind, occurredAt: evidence.occurredAt,
                      conversationId: evidence.conversationId,
                    }, item.conversationId))}
                  </section>)}
                </Space>,
              }
            })()]} />}
          </> },
          { key: 'trajectory', label: '服务轨迹', children: <>
            <EmotionArc
              history={selected.emotionHistory ?? []}
              servicePoints={selected.servicePoints ?? []}
              comparisons={selected.emotionComparisons ?? []}
              onOpenConversation={openConversation}
            />
            {Boolean(selected.emotionHistory?.length) && <section className="service-section"><h3>消费者消息</h3>
              <Timeline items={selected.emotionHistory?.map((point) => ({
                key: point.messageId, content: <div className="service-message-content">
                  <div className="section-title-row"><Space><Tag color={point.emotion === 'angry' ? 'error' : point.emotion === 'dissatisfied' ? 'warning' : 'success'}>{emotionLabels[point.emotion]}</Tag>
                    <span>{dateLabel(point.occurredAt)} · {point.conversationId}</span></Space>
                    <Button type="text" size="small" icon={<MessageOutlined />} aria-label={`打开会话 ${point.conversationId}`} onClick={() => openConversation(point.conversationId)} /></div>
                  <p>{point.body}</p>
                </div>,
              }))} />
            </section>}
            {Boolean(selected.contactHistory?.length) && <section className="service-section"><h3>历史进线</h3>
              {selected.contactHistory?.map((item) => evidenceQuote(item, item.label))}
            </section>}
            {selected.contexts.map((context) => <section className="service-section" key={context.conversationId}>
              <div className="section-title-row"><strong>{context.conversationId}</strong>
                <Space>
                  <Button size="small" icon={<MessageOutlined />} onClick={() => openConversation(context.conversationId)}>打开会话</Button>
                  <Button size="small" icon={<FileTextOutlined />} aria-label={`为会话 ${context.conversationId} 新建工单`}
                    title="为此会话新建工单"
                    onClick={() => navigate(`/platform/work-orders?conversation=${encodeURIComponent(context.conversationId)}&create=1`)} />
                </Space></div>
              <OrderFacts context={context} /><ServiceTimeline context={context} />
            </section>)}
            {selected.handlingHistory.length > 0 && <Collapse ghost items={[{
              key: 'handling', label: '处置记录', children: <Timeline items={selected.handlingHistory.map((event) => ({
                key: event.eventId, content: <div><span>{dateLabel(event.createdAt)} · {event.actor}</span><p>{event.note}</p></div>,
              }))} />,
            }]} />}
            {Boolean(selected.episodes?.length) && <Collapse ghost items={[{
              key: 'episodes', label: '历史轮次', children: selected.episodes?.map((episode) => <section className="service-section" key={`${episode.alertId}-${episode.episode}`}>
                <h3>第 {episode.episode} 轮 · {serviceRiskTypeLabels[episode.riskType as keyof typeof serviceRiskTypeLabels] ?? episode.riskType}</h3>
                <p>{dateLabel(episode.closedAt)} · {episode.handledBy}</p><p>{episode.handledNote}</p>
                {episode.evidence.map((item) => evidenceQuote(item))}
              </section>),
            }]} />}
          </> },
          { key: 'work', label: `关联工单 ${selected.tickets.length}`, children: <>
            <Button disabled={!primaryId} onClick={() => primaryId && navigate(`/platform/work-orders?conversation=${encodeURIComponent(primaryId)}&create=1`)}>新建跟进工单</Button>
            {selected.tickets.map((ticket) => <section className="service-section" key={ticket.ticketId}>
              <div className="section-title-row"><strong>{ticket.title}</strong><TicketStatus status={ticket.status} /></div>
              <p>{ticket.assignee || '待分配'} · {ticket.ticketId}</p>
              <Button size="small" onClick={() => navigate(`/platform/work-orders?ticket=${encodeURIComponent(ticket.ticketId)}`)}>打开工单</Button>
            </section>)}
          </> },
        ]} />
      </>}
    </Drawer>
    <Modal title={action ? actionLabels[action.status] : ''} open={Boolean(action)} onCancel={() => { if (!saving) setAction(null) }}
      onOk={() => void handle()} okText="确认" cancelText="取消" confirmLoading={saving}
      cancelButtonProps={{ disabled: saving }} okButtonProps={{ disabled: !result }}>
      <Select aria-label="处理结果" placeholder="选择处理结果" value={result} onChange={setResult} style={{ width: '100%', marginBottom: 12 }}
        options={(action ? actionResults[action.status] : []).map((value) => ({ value, label: value }))} />
      <Input aria-label="补充备注" placeholder="补充备注（选填）" value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} />
    </Modal>
  </div>
}
