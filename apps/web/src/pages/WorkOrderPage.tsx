import { ArrowLeftOutlined, CloseOutlined, PlusOutlined, ReloadOutlined, SaveOutlined, SearchOutlined } from '@ant-design/icons'
import { Alert, Button, Descriptions, Form, Input, Modal, Segmented, Select, Space, Tabs, Tag, Timeline, message } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { deskApi, supportApi, type ConsumerServiceContextView, type ReceptionItem, type TicketCreateRequest, type TicketUpdateRequest, type TicketView } from '../api/client'
import { PageHeader } from '../components/PageHeader'
import { OrderFacts, dateLabel, optionsOf, priorities, ticketStatuses, ticketTypes } from '../features/service-desk/shared'
import { getDemoOperator, useDemoOperator } from '../features/service-desk/operator'
import { TicketDetailFields, newTicketDetail } from '../features/service-desk/TicketDetailFields'
import { ticketDeadline } from '../features/service-desk/ticketDeadline'
import { TicketTable } from '../features/service-desk/TicketTable'
import { compareTickets, groupOf, matchesQuick, statusGroups, type QuickFilter, type StatusGroup } from '../features/service-desk/ticketList'
import { visibleInterval } from '../hooks/visibleInterval'

const detailLabels: Record<string, string> = {
  serviceType: '工单类型', reason: '售后原因', productName: '商品', sku: '货号', quantity: '数量',
  originalTrackingNo: '原物流号', reshipTrackingNo: '补发物流号', carrier: '快递', warehouse: '发货仓库',
  urgent: '加急', paymentType: '打款类型', refundReason: '退款问题', refundAmount: '退款金额',
  transferStatus: '转账状态', relatedTrackingNo: '关联物流号', issueType: '物流问题',
  trackingNo: '物流单号', solution: '处理方案', skinType: '肤质', productBatchNo: '产品批次',
  affectedArea: '不适部位', symptomDescription: '症状描述', onsetInterval: '出现时间',
  stoppedUse: '是否停用', soughtMedicalCare: '是否就医', parcelType: '包裹类型',
  returnReason: '退货原因', refundId: '退款编号', receiptAdvice: '签收建议', abnormal: '是否异常',
}
const toInputTime = (value?: string | null) => {
  if (!value) return ''
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
type EditValues = Omit<TicketUpdateRequest, 'expectedRevision'>

function TicketHandlingForm({ ticket, operator, saving, onSave }: {
  ticket: TicketView
  operator: string
  saving: boolean
  onSave: (values: EditValues) => Promise<boolean>
}) {
  const [form] = Form.useForm<EditValues>()
  const [detailEditing, setDetailEditing] = useState(Boolean(ticket.localDetail))
  return <Form name="ticket-edit" form={form} layout="vertical" initialValues={{
    status: ticket.status, priority: ticket.priority, assignee: ticket.assignee,
    dueAt: toInputTime(ticket.dueAt), note: '', localDetail: ticket.localDetail ?? newTicketDetail(ticket.workOrderType),
  }} onFinish={async (values) => { if (await onSave(values)) form.setFieldValue('note', '') }}>
    <div className="form-grid"><Form.Item name="status" label="处理状态" rules={[{ required: true }]}><Select options={optionsOf(ticketStatuses)} /></Form.Item>
      <Form.Item name="priority" label="优先级" rules={[{ required: true }]}><Select options={optionsOf(priorities)} /></Form.Item>
      <Form.Item label="负责人" htmlFor="ticket-edit_assignee"><Space.Compact block>
        <Form.Item name="assignee" noStyle><Input maxLength={80} /></Form.Item>
        <Button onClick={() => form.setFieldValue('assignee', operator)}>指派给我</Button>
      </Space.Compact></Form.Item>
      <Form.Item name="dueAt" label="下次跟进"><Input type="datetime-local" /></Form.Item></div>
    {detailEditing ? <TicketDetailFields kind={ticket.workOrderType} initializeDefaults={false} /> : <Button
      icon={<PlusOutlined />} onClick={() => setDetailEditing(true)}>补充事项资料</Button>}
    <Form.Item name="note" label="跟进记录" rules={[{ required: true, whitespace: true, message: '请填写跟进记录' }]}><Input.TextArea rows={3} maxLength={2000} /></Form.Item>
    <Button type="primary" htmlType="submit" icon={<SaveOutlined />} loading={saving}>保存跟进</Button>
  </Form>
}

export function WorkOrderPage() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const [rows, setRows] = useState<TicketView[]>([])
  const [selected, setSelected] = useState<TicketView | null>(null)
  const [context, setContext] = useState<ConsumerServiceContextView | null>(null)
  const [queue, setQueue] = useState<ReceptionItem[]>([])
  const [createContext, setCreateContext] = useState<ConsumerServiceContextView | null>(null)
  const [query, setQuery] = useState(() => params.get('q') ?? '')
  const [status, setStatus] = useState<'all' | StatusGroup>('all')
  const [quick, setQuick] = useState<QuickFilter[]>([])
  const [collapsed, setCollapsed] = useState<ReadonlySet<StatusGroup>>(() => new Set(['resolved']))
  const [type, setType] = useState<string>()
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [createOpen, setCreateOpen] = useState(params.get('create') === '1')
  const [clock, setClock] = useState(Date.now)
  const operator = useDemoOperator()
  const [createForm] = Form.useForm<TicketCreateRequest>()
  const [toast, holder] = message.useMessage()
  const selectedRequest = useRef(0)
  const listRequest = useRef(0)
  const ticketId = params.get('ticket')
  const conversationId = params.get('conversation')
  const createConversation = Form.useWatch('conversationId', createForm)
  const createType = Form.useWatch('workOrderType', createForm)

  const load = useCallback(async (silent = false) => {
    const request = ++listRequest.current
    if (!silent) setLoading(true)
    try {
      const data = await deskApi.tickets()
      if (request === listRequest.current) { setRows(data); setError('') }
    }
    catch (err) { if (request === listRequest.current) setError((err as Error).message) }
    finally { if (request === listRequest.current) setLoading(false) }
  }, [])
  useEffect(() => {
    void load()
    const stop = visibleInterval(() => { setClock(Date.now()); void load(true) }, 15000)
    return () => { stop(); listRequest.current++ }
  }, [load])
  useEffect(() => {
    const request = ++selectedRequest.current
    setSelected(null); setContext(null)
    if (!ticketId) return
    void deskApi.ticket(ticketId).then(async (ticket) => {
      if (request !== selectedRequest.current) return
      setSelected(ticket)
      const facts = await supportApi.serviceContext(ticket.conversationId)
      if (request === selectedRequest.current) setContext(facts)
    }).catch((err: Error) => { if (request === selectedRequest.current) setError(err.message) })
    return () => { selectedRequest.current++ }
  }, [ticketId])
  useEffect(() => {
    if (!createOpen) return
    let active = true
    void supportApi.reception().then((data) => { if (active) setQueue(data.items) }).catch((err: Error) => setError(err.message))
    createForm.setFieldsValue({ title: '', note: '', dueAt: '', orderId: undefined,
      conversationId: conversationId ?? undefined, priority: 'normal', workOrderType: 'logistics', assignee: getDemoOperator() })
    createForm.setFieldValue('localDetail', newTicketDetail('logistics'))
    return () => { active = false }
  }, [createOpen, createForm, conversationId])
  useEffect(() => {
    if (createType) createForm.setFieldValue('localDetail', newTicketDetail(createType))
  }, [createType, createForm])
  useEffect(() => {
    let active = true
    setCreateContext(null); createForm.setFieldValue('orderId', undefined)
    if (createConversation) void supportApi.serviceContext(createConversation).then((data) => {
      if (active) setCreateContext(data)
    }).catch((err: Error) => setError(err.message))
    return () => { active = false }
  }, [createConversation, createForm])

  const save = async (values: EditValues) => {
    if (!selected) return false
    setSaving(true)
    try {
      const result = await deskApi.updateTicket(selected.ticketId, {
        ...values, expectedRevision: selected.revision,
        dueAt: values.dueAt ? new Date(values.dueAt).toISOString() : null,
      })
      setSelected(result); void toast.success('已保存')
      await load()
      return true
    } catch (err) { void toast.error((err as Error).message); return false }
    finally { setSaving(false) }
  }
  const create = async (values: TicketCreateRequest) => {
    setSaving(true)
    try {
      const result = await deskApi.createTicket({ ...values, dueAt: values.dueAt ? new Date(values.dueAt).toISOString() : null })
      setCreateOpen(false); setParams({ ticket: result.ticketId })
      await load()
    } catch (err) { void toast.error((err as Error).message) }
    finally { setSaving(false) }
  }
  const scoped = useMemo(() => rows.filter((row) => (!type || row.workOrderType === type)
    && (!conversationId || row.conversationId === conversationId)
    && `${row.ticketId} ${row.title} ${row.buyerAlias} ${row.orderId ?? ''} ${row.assignee}`.includes(query)
    && matchesQuick(row, quick, operator, clock)), [rows, type, conversationId, query, quick, operator, clock])
  const filtered = useMemo(() => scoped.filter((row) => status === 'all' || groupOf(row.status) === status)
    .sort((a, b) => compareTickets(a, b, clock)), [scoped, status, clock])
  const grouped = status === 'all'
  const navOrder = useMemo(() => filtered.filter((row) => !grouped || !collapsed.has(groupOf(row.status))).map((row) => row.ticketId),
    [filtered, grouped, collapsed])
  const open = useCallback((id: string | null) => setParams(id ? { ticket: id } : {}), [setParams])
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('input, textarea, select, [contenteditable="true"], .ant-select, .ant-modal')) return
      if (event.key === 'Escape' && ticketId) { open(null); return }
      if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return
      if (!navOrder.length) return
      const at = ticketId ? navOrder.indexOf(ticketId) : -1
      const next = event.key === 'ArrowDown' ? Math.min(navOrder.length - 1, at + 1) : Math.max(0, at - 1)
      if (navOrder[next] !== ticketId) { event.preventDefault(); open(navOrder[next]) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [navOrder, ticketId, open])
  const toggleQuick = (key: QuickFilter) => setQuick((cur) => cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key])
  const toggleGroup = (group: StatusGroup) => setCollapsed((cur) => {
    const next = new Set(cur); if (next.has(group)) next.delete(group); else next.add(group); return next
  })
  const countOf = (group: StatusGroup) => scoped.filter((row) => groupOf(row.status) === group).length

  return <div className="desk-workbench">{holder}
    <PageHeader title="工单管理" stats={[
      { label: '全部工单', value: rows.length },
      { label: '我的待办', value: rows.filter((r) => r.status !== 'resolved' && r.assignee === operator).length },
      { label: '已到期', value: rows.filter((r) => ticketDeadline(r, clock) === 'overdue').length, warning: true },
      { label: '24小时内', value: rows.filter((r) => ticketDeadline(r, clock) === 'soon').length },
      { label: '已完成', value: rows.filter((r) => r.status === 'resolved').length },
    ]} actions={<Space><Button icon={<ReloadOutlined />} aria-label="刷新工单" loading={loading} onClick={() => void load()} />
      <Button type="primary" icon={<PlusOutlined />} aria-label="新建工单" onClick={() => setCreateOpen(true)}>新建工单</Button></Space>} />
    <div className={`desk-page-body yt-ticket-page${ticketId ? ' has-detail' : ''}`}>
      <div className="yt-ticket-list">
        {error && <Alert type="error" title={error} showIcon />}
        <div className="desk-filterbar">
          <Segmented aria-label="处理状态" value={status} onChange={(v) => setStatus(v as typeof status)} options={[
            { value: 'all', label: `全部 ${scoped.length}` },
            ...statusGroups.map(({ key, label }) => ({ value: key, label: `${label} ${countOf(key)}` })),
          ]} />
          <span className="yt-quick-group" role="group" aria-label="快捷筛选">
            {([['mine', '我的'], ['unassigned', '待分配'], ['due', '到期']] as const).map(([key, label]) =>
              <button key={key} type="button" className="yt-quick" aria-pressed={quick.includes(key)} onClick={() => toggleQuick(key)}>{label}</button>)}
          </span>
          <Input aria-label="搜索工单" prefix={<SearchOutlined />} placeholder="工单、订单、客户、负责人" value={query} onChange={(e) => setQuery(e.target.value)} allowClear />
          <Select aria-label="工单类型" placeholder="工单类型" value={type} options={optionsOf(ticketTypes)} onChange={setType} allowClear />
          {conversationId && <Tag closable onClose={() => setParams({})}>{conversationId}</Tag>}
        </div>
        <TicketTable rows={filtered} grouped={grouped} collapsed={collapsed} onToggle={toggleGroup} selectedId={ticketId}
          onOpen={open} now={clock} compact={Boolean(ticketId)} loading={loading} />
      </div>
      {ticketId && <aside className="yt-ticket-detail" aria-label="工单详情">
        <header><h2>{selected?.title ?? '工单详情'}</h2>
          {selected && <Tag>{selected.ticketId}</Tag>}
          {selected && <Button size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate(`/support?conversation=${selected.conversationId}`)}>打开会话</Button>}
          <Button type="text" size="small" aria-label="关闭" icon={<CloseOutlined />} onClick={() => open(null)} /></header>
        {selected && <div className="yt-ticket-detail-body">
          <Tabs items={[
            { key: 'handling', label: '处理与跟进', children: <>
              <Descriptions column={2} size="small" items={[
                { key: 'type', label: '类型', children: ticketTypes[selected.workOrderType] },
                { key: 'source', label: '源工单状态', children: selected.sourceStatus || '本地新建' },
                { key: 'customer', label: '客户', children: selected.buyerAlias },
                { key: 'order', label: '订单', children: selected.orderId || '未关联' },
              ]} />
              <TicketHandlingForm key={selected.ticketId} ticket={selected} operator={operator} saving={saving} onSave={save} />
              <section className="service-section"><h3>处理记录</h3><Timeline items={(selected.events ?? []).map((e) => ({
                key: e.eventId, content: <div><small>{dateLabel(e.createdAt)} · {e.actor}</small><p>{e.note}</p></div>,
              }))} /></section>
            </> },
            ...(selected.sourceRecordId ? [{ key: 'source', label: '源工单', children: <Descriptions column={1} bordered size="small" items={Object.entries(detailLabels).filter(([key]) => selected.detail?.[key] != null).map(([key, label]) => ({
              key, label, children: String(selected.detail?.[key]),
            }))} /> }] : []),
            { key: 'order', label: '订单商品', children: <OrderFacts context={context} /> },
          ]} />
        </div>}
      </aside>}
    </div>
    <Modal title="新建工单" open={createOpen} onCancel={() => { setCreateOpen(false); if (params.has('create')) setParams({}) }}
      onOk={() => createForm.submit()} confirmLoading={saving} okText="创建" cancelText="取消" width={640} forceRender>
      <Form name="ticket-create" form={createForm} layout="vertical" onFinish={(values) => void create(values)}>
        <Form.Item name="title" label="事项" rules={[{ required: true, whitespace: true, message: '请填写事项' }]}><Input maxLength={200} /></Form.Item>
        <div className="form-grid">
          <Form.Item name="conversationId" label="客户会话" rules={[{ required: true, message: '请选择会话' }]}><Select showSearch={{ optionFilterProp: 'label' }} options={queue.map((q) => ({ value: q.conversationId, label: `${q.buyerAlias} · ${q.conversationId}` }))} /></Form.Item>
          <Form.Item name="orderId" label="关联订单"><Select allowClear options={createContext?.orders.map((o) => ({ value: o.orderId, label: `${o.orderId} · ${o.productName}` }))} /></Form.Item>
          <Form.Item name="workOrderType" label="工单类型" rules={[{ required: true }]}><Select options={optionsOf(ticketTypes)} /></Form.Item>
          <Form.Item name="priority" label="优先级"><Select options={optionsOf(priorities)} /></Form.Item>
          <Form.Item name="assignee" label="负责人"><Input /></Form.Item>
          <Form.Item name="dueAt" label="下次跟进"><Input type="datetime-local" /></Form.Item>
        </div>
        {createType && <TicketDetailFields key={createType} kind={createType} />}
        <Form.Item name="note" label="事项说明" rules={[{ required: true, whitespace: true, message: '请填写事项说明' }]}><Input.TextArea rows={4} maxLength={2000} /></Form.Item>
      </Form>
    </Modal>
  </div>
}
