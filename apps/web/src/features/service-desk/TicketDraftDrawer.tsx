import { Button, Drawer, Form, Input, Select, Spin, Tooltip, message } from 'antd'
import { useEffect, useState } from 'react'
import { deskApi, type ConsumerServiceContextView, type TicketCreateRequest, type TicketDraftView, type TicketView } from '../../api/client'
import { priorities, ticketTypes, optionsOf } from './shared'
import { TicketDetailFields } from './TicketDetailFields'
import { draftToFormValues } from './ticketDraft'

const FIELD_LABELS: Record<string, string> = {
  symptomDescription: '症状', affectedArea: '部位', onsetInterval: '出现时间', productBatchNo: '批次',
  stoppedUse: '是否停用', soughtMedicalCare: '是否就医', reason: '诉求',
}

/** 工作台内建工单（P1-4）：按原话预填，客服确认后才创建本地工单。 */
export function TicketDraftDrawer({ open, conversationId, buyerAlias, context, onClose, onCreated }: {
  open: boolean; conversationId: string | null; buyerAlias?: string
  context: ConsumerServiceContextView | null
  onClose: () => void; onCreated: (ticket: TicketView) => void
}) {
  const [form] = Form.useForm<TicketCreateRequest>()
  const [draft, setDraft] = useState<TicketDraftView | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [toast, holder] = message.useMessage()
  const kind = Form.useWatch('workOrderType', form)

  useEffect(() => {
    if (!open || !conversationId) return
    let cancelled = false
    setLoading(true); setDraft(null); form.resetFields()
    deskApi.ticketDraft(conversationId).then((next) => {
      if (cancelled) return
      setDraft(next)
      const values = draftToFormValues(next)
      const type = values.workOrderType
      form.setFieldsValue({
        ...values, conversationId, priority: next.workOrderType === 'adverse_reaction' ? 'high' : 'normal',
        title: type ? `${ticketTypes[type]} · ${buyerAlias ?? conversationId}` : '',
        note: next.fields.map((item) => `${FIELD_LABELS[item.field] ?? item.field}：${item.quote}`).join('\n'),
      })
    }).catch((err: Error) => { if (!cancelled) void toast.error(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [open, conversationId, buyerAlias, form, toast])

  const submit = async (values: TicketCreateRequest) => {
    setSaving(true)
    try {
      const ticket = await deskApi.createTicket({ ...values, conversationId: conversationId ?? values.conversationId,
        dueAt: values.dueAt ? new Date(values.dueAt).toISOString() : null })
      void toast.success('已创建工单')
      onCreated(ticket)
    } catch (err) { void toast.error((err as Error).message) }
    finally { setSaving(false) }
  }

  return <Drawer title="新建工单" size={520} open={open} onClose={onClose} destroyOnHidden
    styles={{ wrapper: { maxWidth: '100vw' } }}
    extra={<Button type="primary" loading={saving} disabled={loading} onClick={() => form.submit()}>创建</Button>}>
    {holder}
    {loading ? <Spin /> : <Form name="desk-ticket-create" form={form} layout="vertical" onFinish={(values) => void submit(values)}>
      {draft && draft.fields.length > 0 && <div className="yt-draft-sources" aria-label="预填依据">
        {draft.fields.map((item) => <Tooltip key={item.field} title={item.quote}>
          <span className="yt-memory-tag">{FIELD_LABELS[item.field] ?? item.field}</span>
        </Tooltip>)}
      </div>}
      <Form.Item name="conversationId" hidden><Input /></Form.Item>
      <Form.Item name="title" label="事项" rules={[{ required: true, whitespace: true, message: '请填写事项' }]}><Input maxLength={200} /></Form.Item>
      <div className="form-grid">
        <Form.Item name="workOrderType" label="工单类型" rules={[{ required: true, message: '请选择工单类型' }]}><Select options={optionsOf(ticketTypes)} /></Form.Item>
        <Form.Item name="orderId" label="关联订单"><Select allowClear options={context?.orders.map((o) => ({ value: o.orderId, label: `${o.orderId} · ${o.productName}` }))} /></Form.Item>
        <Form.Item name="priority" label="优先级"><Select options={optionsOf(priorities)} /></Form.Item>
        <Form.Item name="dueAt" label="下次跟进"><Input type="datetime-local" /></Form.Item>
      </div>
      {kind && <TicketDetailFields key={kind} kind={kind} initializeDefaults={kind !== draft?.workOrderType} />}
      <Form.Item name="note" label="事项说明" rules={[{ required: true, whitespace: true, message: '请填写事项说明' }]}><Input.TextArea rows={4} maxLength={2000} /></Form.Item>
    </Form>}
  </Drawer>
}
