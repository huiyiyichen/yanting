import { ApartmentOutlined, CheckOutlined, CloseOutlined, MessageOutlined, MoreOutlined, PlayCircleOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import { Alert, Button, Dropdown, Empty, Input, Modal, Select, Skeleton, Space, Table, Tabs, Tag, message } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, deskApi, supportApi, type DateRange, type ProductClueView, type ConsumerProfileView, type ReceptionItem, type RiskIncidentDetailView, type RiskIncidentView, type RiskOverviewView } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import { dateLabel, optionsOf } from '../features/service-desk/shared'
import { serviceRiskTypeLabels } from '../contracts/enums'
import { emotionStatus, primaryConversation, signalAttention } from '../features/service-desk/riskPresentation'
import { RiskSpark } from '../features/risk/RiskSpark'
import { RiskOverviewPanel } from '../features/risk/RiskOverviewPanel'
import { RiskConclusion } from '../features/risk/RiskConclusion'
import { ConversationReplay, type ReplayHandle } from '../features/risk/ConversationReplay'
import { ServiceTrack } from '../features/risk/ServiceTrack'
import { RiskTicketList } from '../features/risk/RiskDetailMore'
import { FollowUpButton, FollowUpChip } from '../features/risk/FollowUp'
import { visibleInterval } from '../hooks/visibleInterval'

const actionLabels = { resolved: '复核关闭', ignored: '忽略风险', reopen: '重新介入' }
const actionResults = {
  resolved: ['已核对，风险已消退', '消费者确认问题已解决', '已核实无需继续跟进'],
  ignored: ['重复预警', '无需跟进', '记录不适用'],
  reopen: ['需重新核对', '出现新的待处理事项'],
}
const levelLabels: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险', unknown: '未知' }
const serviceStateLabels: Record<string, string> = { live: '服务中', closed: '服务已结束', historical: '历史记录' }
const currentActionLabels: Record<string, string> = { intervene: '待处理', review: '待复核', record_only: '历史记录', none: '已归档' }
type Signal = RiskIncidentView['signals'][number]
type RiskAction = { status: keyof typeof actionLabels; incidentId: string; expectedVersion: string }

function signalState(signal: Signal, incident: RiskIncidentView) {
  const judgment = incident.judgments?.find((item) => item.alertId === signal.alertId)
  if (judgment?.verdict === 'false_positive' && !judgment.stale) return '已标误报'
  return { active: '当前触发', review: '待复核', historical: '历史信号', closed: '已关闭' }[signalAttention(signal)]
}

/** 风险结论行只保留有意义的状态；历史信号不再占位（反馈 10-18 #2） */
function conclusionState(state: string) {
  return state === '历史信号' ? null : state
}

export function RiskDashboardPage() {
  const [rows, setRows] = useState<RiskIncidentView[]>([])
  const [receptionItems, setReceptionItems] = useState<ReceptionItem[]>([])
  const [selected, setSelected] = useState<RiskIncidentDetailView | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState<'replay' | 'lanes'>('replay')
  const replayRef = useRef<ReplayHandle>(null)
  const [query, setQuery] = useState('')
  const [scopeState, setScope] = useState<'initial' | 'official' | 'live'>('initial')
  const [tab, setTab] = useState<'initial' | 'active' | 'review' | 'closed' | 'all'>('initial')
  const [type, setType] = useState<string>()
  const [level, setLevel] = useState<string>()
  const [error, setError] = useState('')
  const [runtimeWarning, setRuntimeWarning] = useState(false)
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [action, setAction] = useState<RiskAction | null>(null)
  const [result, setResult] = useState<string>()
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [overview, setOverview] = useState<RiskOverviewView | null>(null)
  const [clues, setClues] = useState<ProductClueView[]>([])
  const [detailProfile, setDetailProfile] = useState<ConsumerProfileView | null>(null)
  const [toast, holder] = message.useMessage()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const rangeFrom = searchParams.get('from'), rangeTo = searchParams.get('to')
  const range = useMemo(() => rangeFrom && rangeTo ? { from: rangeFrom, to: rangeTo } : null, [rangeFrom, rangeTo])
  // X-1：框选时间段写入 URL（from/to），刷新保留
  const setRange = useCallback((next: DateRange | null) => setSearchParams((old) => {
    const params = new URLSearchParams(old)
    if (next) { params.set('from', next.from); params.set('to', next.to) } else { params.delete('from'); params.delete('to') }
    return params
  }, { replace: true }), [setSearchParams])
  const [hotConversation, setHotConversation] = useState<string | null>(null)
  const [page, setPage] = useState(1)
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
        setScope((current) => current === 'initial'
          ? data.some((row) => row.currentAction === 'record_only') ? 'official' : 'live'
          : current)
        setRuntimeWarning(data.some((row) => !row.serviceState || !row.currentAction))
        setError('')
      }
      return data
    } catch (err) { if (request === listRequest.current) setError((err as Error).message) }
    finally { if (request === listRequest.current) setLoading(false) }
  }, [])
  const scope: 'official' | 'live' = scopeState === 'live' ? 'live' : 'official'
  const mode = scope === 'official' ? 'historical' : 'active'
  useEffect(() => {
    let cancelled = false
    Promise.all([deskApi.riskOverview(scope, range), deskApi.productClues(range)])
      .then(([nextOverview, nextClues]) => {
        if (cancelled) return
        setOverview(nextOverview?.counts ? nextOverview : null)
        setClues(Array.isArray(nextClues) ? nextClues : [])
      })
      .catch(() => undefined)
    return () => { cancelled = true }
  }, [scope, scanning, range])
  useEffect(() => {
    void load()
    const sync = () => { if (!document.hidden) void load(true) }
    const stop = visibleInterval(sync, 10000)
    window.addEventListener('focus', sync)
    return () => { stop(); window.removeEventListener('focus', sync); listRequest.current++ }
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
      setScope(row.currentAction === 'record_only' ? 'official' : 'live')
      setTab(row.attentionState === 'review' || row.currentAction === 'review' ? 'review'
        : row.attentionState === 'closed' ? 'closed' : row.currentAction === 'record_only' ? 'all' : 'active')
    }
  }, [requestedConversation, requestedType, requestedIncident, rows])
  const openConversation = (id: string) => navigate(`/support?conversation=${encodeURIComponent(id)}`)
  const closeDetail = () => { setSelectedId(null); setAction(null) }
  useEffect(() => {
    if (!selectedId && !range) return
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (event.key !== 'Escape' || target?.closest('input, textarea, [contenteditable="true"], .ant-modal')) return
      // Esc 先关详情，再清时间段
      if (selectedId) { setSelectedId(null); setAction(null) } else setRange(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, range, setRange])
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
  const rangeIds = range && overview?.rangeConversationIds ? new Set(overview.rangeConversationIds) : null
  const inScope = rows.filter((row) => (row.currentAction === 'record_only') === (scope === 'official')
    && (!rangeIds || row.conversationIds.some((cid) => rangeIds.has(cid))))
  // 跟进到期的风险回到待处理（用户反馈 10-18 #7）
  const tabOf = (row: RiskIncidentView) => row.followUpDue ? 'active' : row.attentionState === 'closed' ? 'closed'
    : row.currentAction === 'review' || row.attentionState === 'review' ? 'review'
      : row.currentAction === 'intervene' ? 'active' : 'other'
  const counts = { active: inScope.filter((row) => tabOf(row) === 'active').length, review: inScope.filter((row) => tabOf(row) === 'review').length }
  const currentTab = tab === 'initial' ? (counts.active ? 'active' : 'all') : tab
  const safeCustomers = receptionItems.filter((item) =>
    item.dataSource === 'live' && !item.activeRiskTypes?.length && !item.reviewRiskTypes?.length)
  const showSafe = level === 'none'
  const filtered = inScope.filter((row) =>
    (currentTab === 'all' || tabOf(row) === currentTab)
    && (!level || row.riskLevel === level)
    && (!type || row.signals.some((signal) => signal.riskType === type && (mode !== 'active' || signalAttention(signal) === 'active')))
    && `${row.buyerAlias} ${row.conversationIds.join(' ')} ${row.orderIds.join(' ')} ${row.latestMessage}`.includes(query))
  const safeFiltered = safeCustomers.filter((item) =>
    `${item.buyerAlias} ${item.conversationId} ${item.preview}`.includes(query))
  const incident = selected?.incident
  const primaryId = incident && primaryConversation(incident)
  useEffect(() => {
    if (!primaryId) return
    let cancelled = false
    supportApi.profile(primaryId).then((data) => { if (!cancelled) setDetailProfile(data) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [primaryId])
  const openTicket = selected?.tickets.find((ticket) => ticket.status !== 'resolved')
  const signalGroups = new Map<string, Signal[]>()
  for (const signal of incident?.signals ?? []) {
    const group = signalGroups.get(signal.riskType) ?? []
    group.push(signal)
    signalGroups.set(signal.riskType, group)
  }
  return <div className="desk-workbench yt-risk-page">{holder}
    <PageHeader title="风险预警" extra={<div className="yt-scope" role="radiogroup" aria-label="数据范围">
      {(['official', 'live'] as const).map((key) => <button key={key} type="button" role="radio" aria-checked={scope === key}
        className={scope === key ? 'on' : undefined}
        onClick={() => { setScope(key); setTab('initial') }}>{key === 'official' ? '官方记录' : '实时'}</button>)}
    </div>} actions={<Space><Button icon={<ReloadOutlined />} aria-label="刷新风险" loading={loading} onClick={() => void load()} />
      <Button icon={<PlayCircleOutlined />} loading={scanning} onClick={() => void scan()}>扫描异常</Button></Space>} />
    <div className="desk-page-body">
      {error && <Alert type="error" title={error} showIcon />}
      {runtimeWarning && <Alert type="warning" title="风险接口版本过旧，请更新后端" showIcon />}
      {overview && <RiskOverviewPanel overview={overview} clues={clues}
        onFilterType={(next) => setType(next)} onFilterConversation={(cid) => setQuery(cid)}
        range={range} onRange={(next) => { setRange(next); setPage(1) }} hotConversation={hotConversation}
        onMarker={(cid) => {
          // 点菱形：选中对应列表行并滚动到可见
          const at = filtered.findIndex((row) => row.conversationIds.includes(cid))
          if (at < 0) { setQuery(cid); return }
          setPage(Math.floor(at / 10) + 1); setSelectedId(filtered[at].incidentId)
          requestAnimationFrame(() => document.querySelector(`[data-row-key="${filtered[at].incidentId}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
        }} />}
      <div className={`yt-risk-md${selectedId ? ' has-detail' : ''}`}>
      <section className="yt-risk-queue" aria-label="风险队列">
      <Tabs activeKey={currentTab} onChange={(key) => setTab(key as typeof tab)} items={[
        { key: 'active', label: `待处理 ${counts.active}` }, { key: 'review', label: `待复核 ${counts.review}` },
        { key: 'closed', label: '已关闭' }, { key: 'all', label: `全部 ${inScope.length}` },
      ]} />
      <div className="desk-filterbar">
        <Input prefix={<SearchOutlined />} aria-label="搜索风险" placeholder="客户、订单、最新消息" allowClear value={query} onChange={(e) => setQuery(e.target.value)} />
        <Select aria-label="风险等级" placeholder="风险等级" allowClear value={level} onChange={setLevel} options={[...optionsOf(levelLabels), ...(scope === 'live' ? [{ value: 'none', label: '无风险' }] : [])]} />
        <Select aria-label="风险类型" placeholder="风险类型" allowClear value={type} onChange={setType} options={optionsOf(serviceRiskTypeLabels)} />
      </div>
      {showSafe ? <Table<ReceptionItem> rowKey="conversationId" size="small" dataSource={safeFiltered} loading={loading}
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
        ]} /> : <Table<RiskIncidentView> rowKey="incidentId" size="small" rowClassName={(row) => `yt-rk-row is-${row.riskLevel}${row.incidentId === selectedId ? ' is-selected' : ''}`}
        onRow={(row) => ({ onClick: () => setSelectedId(row.incidentId), 'aria-selected': row.incidentId === selectedId,
          onMouseEnter: () => setHotConversation(row.conversationIds[0] ?? null), onMouseLeave: () => setHotConversation(null) })}
        dataSource={filtered} loading={loading} scroll={{ x: 1000 }}
        pagination={{ pageSize: 10, showSizeChanger: false, current: Math.min(page, Math.max(1, Math.ceil(filtered.length / 10))), onChange: setPage }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={runtimeWarning ? '当前预警未加载' : '暂无风险事件'} /> }}
        columns={[
          { title: '等级 / 状态', width: 125, render: (_, row) => <div className="table-cell-stack">
            <Tag color={row.riskLevel === 'high' ? 'error' : row.riskLevel === 'medium' ? 'warning' : 'default'}>{levelLabels[row.riskLevel]}</Tag>
            <span className={`yt-rk-status is-${row.currentAction}`}>{row.currentAction === 'intervene' && row.riskStatus === 'in_progress' ? '处理中' : currentActionLabels[row.currentAction]}</span>
          </div> },
          { title: '消费者', width: 180, render: (_, row) => <div className="table-cell-stack"><strong className="yt-rk-name" data-testid={`risk-open-${row.incidentId}`} title={row.buyerAlias}>{row.buyerAlias}</strong>{row.serviceState !== 'historical' && <span>{serviceStateLabels[row.serviceState]}</span>}</div> },
          { title: '风险 / 原话', width: 330, render: (_, row) => {
            const signals = row.signals.filter((signal) => mode !== 'active' || signalAttention(signal) === 'active')
            const unique = [...new Map(signals.map((signal) => [`${signal.riskType}:${signalAttention(signal)}`, signal])).values()]
            const shown = unique.slice(0, 2)
            return <div className="table-cell-stack"><Space size={[0, 4]} wrap>{shown.map((signal) => <Tag
              color={signalAttention(signal) === 'active' ? 'warning' : 'default'} key={`${signal.riskType}:${signalAttention(signal)}`}>
              {serviceRiskTypeLabels[signal.riskType]}
            </Tag>)}{unique.length > 2 && <Tag title={unique.slice(2).map((signal) => serviceRiskTypeLabels[signal.riskType]).join('、')}>+{unique.length - 2}</Tag>}</Space>
              <div className="table-excerpt" title={row.latestMessage}>{row.latestMessage || '—'}</div></div>
          } },
          { title: '情绪走势', width: 150, render: (_, row) => <div className="yt-rk-emo"><RiskSpark seq={row.emotionSeq} /><span className={`yt-rk-emo-l is-${row.currentEmotion}`}><i />{emotionStatus(row)}</span></div> },
          { title: '最近消息', width: 120, render: (_, row) => <span className="yt-rk-time">{dateLabel(row.latestCustomerAt)}</span> },
          { title: '', width: 56, render: (_, row) => <Button aria-label={`打开会话 ${row.buyerAlias}`} title="打开会话" size="small" icon={<MessageOutlined />} disabled={!primaryConversation(row)}
            onClick={(event) => { event.stopPropagation(); const id = primaryConversation(row); if (id) openConversation(id) }} /> },
        ]} />}
      </section>
      {selectedId && <aside className="yt-risk-detail" aria-label="风险详情">
      <Button className="yt-risk-close" type="text" size="small" icon={<CloseOutlined />} aria-label="Close" onClick={closeDetail} />
      {selectedId && !selected && <Skeleton active paragraph={{ rows: 8 }} />}
      {selected && incident && <>
        <div className="yt-risk-id">
          <span className="yt-risk-avatar" aria-hidden>{incident.buyerAlias.slice(0, 1)}</span>
          <div><h2>{incident.buyerAlias}</h2><div className="yt-risk-sub">{primaryId} {dateLabel(incident.latestCustomerAt)}<FollowUpChip incident={incident} /></div></div>
        </div>
        <div className="yt-risk-tags"><Space size={[6, 6]} wrap>
          <span className={`yt-cap is-${incident.riskLevel}`}>{levelLabels[incident.riskLevel]}</span>
          <span className="yt-cap is-state">{currentActionLabels[incident.currentAction] ?? incident.currentAction}</span>
        </Space></div>
        <div className="risk-actions">
          <Button type="primary" icon={<MessageOutlined />} disabled={!primaryId} onClick={() => primaryId && openConversation(primaryId)}>打开会话</Button>
          {incident.currentAction === 'intervene' && incident.serviceState === 'live' &&
            <Button icon={<PlayCircleOutlined />} loading={saving} disabled={!primaryId} onClick={() => void takeOver()}>开始处理</Button>}
          {incident.currentAction === 'intervene' && incident.serviceState !== 'live' && openTicket &&
            <Button onClick={() => navigate(`/platform/work-orders?ticket=${encodeURIComponent(openTicket.ticketId)}`)}>跟进工单</Button>}
          <Button icon={<CheckOutlined />} disabled={!(incident.riskStatus === 'in_progress'
            || (incident.riskStatus === 'pending' && incident.attentionState === 'review' && incident.currentAction === 'review'))}
            onClick={() => beginAction('resolved')}>复核关闭</Button>
          {['pending', 'in_progress'].includes(incident.riskStatus) && <FollowUpButton incident={incident}
            onSaved={(detail) => { setSelected(detail); void load(true) }} />}
          <Dropdown menu={{ items: [
            { key: 'ignored', label: '忽略风险', icon: <CloseOutlined />, disabled: !['pending', 'in_progress'].includes(incident.riskStatus) },
            { key: 'reopen', label: '重新介入', icon: <ReloadOutlined />, disabled: !['resolved', 'ignored'].includes(incident.riskStatus) },
            { type: 'divider' },
            { key: 'trace', label: '查看 Agent 追踪', icon: <ApartmentOutlined />, disabled: !primaryId },
          ], onClick: ({ key }) => key === 'trace'
            ? primaryId && navigate(`/platform/models?tab=trace&conversation=${encodeURIComponent(primaryId)}`)
            : beginAction(key as RiskAction['status']) }}>
            <Button aria-label="更多处置" title="更多处置" icon={<MoreOutlined />} />
          </Dropdown>
        </div>
        <RiskConclusion onJump={(cid, mid, hint) => { setDetailTab('replay'); window.setTimeout(() => replayRef.current?.focus(cid, mid, hint), 0) }}
          footer={incident.historicalSensitivity > 0 ? `近 3 次进线中 ${incident.historicalSensitivity} 次有风险` : null}
          rows={[...signalGroups.values()].map((group) => {
            const signal = group.find((item) => signalAttention(item) === 'active') ?? group[0]
            const evidence = group.flatMap((item) => (item.evidenceRefs ?? []).flatMap((ref) => {
              const point = selected.evidence.find((entry) => entry.ref === ref)
              return point ? [{ ...point, conversationId: point.conversationId ?? (incident.conversationIds.includes(point.label) ? point.label : item.conversationId) }] : []
            }))
            const quote = evidence.find((item) => item.kind === 'message' && item.body)
            const fact = evidence.find((item) => item.kind !== 'message' && item.kind !== 'source' && item.body)
            const targets = group.filter((item) => !['resolved', 'ignored'].includes(item.riskStatus))
            return { key: signal.riskType, level: signal.riskLevel, type: serviceRiskTypeLabels[signal.riskType],
              text: quote?.body ?? (fact ? `${fact.label} ${fact.body}` : signal.triggerSummary), highlights: quote?.highlights,
              at: quote?.occurredAt ?? fact?.occurredAt, jump: quote?.conversationId ? { conversationId: quote.conversationId, messageId: quote.ref }
                : { conversationId: fact?.conversationId ?? signal.conversationId, messageId: '', riskType: signal.riskType, at: fact?.occurredAt ?? signal.createdAt },
              state: conclusionState(signalState(signal, incident)),
              tools: targets.length > 0 ? <Dropdown menu={{ items: targets.map((item) => ({
                  key: item.alertId, label: `${signalState(item, incident) === '已标误报' ? '恢复预警' : '标记误报'}${targets.length > 1 ? ` · ${item.conversationId}` : ''}`,
                })), onClick: ({ key }) => {
                  const target = targets.find((item) => item.alertId === key)
                  if (!target) return
                  const restore = signalState(target, incident) === '已标误报'
                  Modal.confirm({ title: restore ? '恢复这条预警？' : '将这条预警标记为误报？',
                    okText: '确认', cancelText: '取消', onOk: () => feedback(target, restore) })
                } }}><Button size="small" type="text" icon={<MoreOutlined />} aria-label={`信号操作 ${signal.alertId}`} disabled={saving} /></Dropdown> : null }
          })} />
        <Tabs className="yt-detail-tabs" activeKey={detailTab} onChange={(key) => setDetailTab(key as typeof detailTab)} items={[
          { key: 'replay', label: '对话回放', children: <ConversationReplay ref={replayRef} key={incident.incidentId}
            conversationIds={incident.conversationIds} primaryId={primaryId ?? null} alias={incident.buyerAlias} /> },
          { key: 'lanes', label: '服务轨迹', children: <>
            <ServiceTrack detail={selected} profile={detailProfile?.conversationId === primaryId ? detailProfile : null}
              onContact={(cid) => { setDetailTab('replay'); window.setTimeout(() => replayRef.current?.focus(cid, ''), 0) }} />
            {selected.tickets.length > 0 && <section className="yt-d-sec" aria-label="关联工单"><h3>关联工单 {selected.tickets.length}</h3>
              <RiskTicketList tickets={selected.tickets} primaryId={primaryId} onNavigate={navigate} /></section>}
          </> },
        ]} />
      </>}
      </aside>}
      </div>
    </div>
    <Modal title={action ? actionLabels[action.status] : ''} open={Boolean(action)} onCancel={() => { if (!saving) setAction(null) }}
      onOk={() => void handle()} okText="确认" cancelText="取消" confirmLoading={saving}
      cancelButtonProps={{ disabled: saving }} okButtonProps={{ disabled: !result }}>
      <Select aria-label="处理结果" placeholder="选择处理结果" value={result} onChange={setResult} style={{ width: '100%', marginBottom: 12 }}
        options={(action ? actionResults[action.status] : []).map((value) => ({ value, label: value }))} />
      <Input aria-label="补充备注" placeholder="补充备注（选填）" value={note} onChange={(event) => setNote(event.target.value)} maxLength={1000} />
    </Modal>
  </div>
}
