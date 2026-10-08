import { Form, Input, InputNumber, Radio, Select } from 'antd'
import type { TicketDetail, TicketView } from '../../api/client'

export function newTicketDetail(kind: TicketView['workOrderType']): Partial<TicketDetail> {
  switch (kind) {
    case 'reship_exchange': return { kind, resolution: 'reship', quantity: 1 }
    case 'offline_payment': return { kind, paymentType: 'refund' }
    case 'logistics': return { kind, issueType: 'tracking_query' }
    case 'adverse_reaction': return { kind, stoppedUse: 'unknown', soughtMedicalCare: 'unknown' }
    case 'return_refund': return { kind, requestType: 'return_refund', parcelType: 'unknown' }
  }
}

const required = [{ required: true, message: '请填写此项' }]
const textRequired = [{ required: true, whitespace: true, message: '请填写此项' }]
const yesNo = [{ value: 'yes', label: '是' }, { value: 'no', label: '否' }, { value: 'unknown', label: '未知' }]

export function TicketDetailFields({ kind, initializeDefaults = true }: {
  kind: TicketView['workOrderType']
  initializeDefaults?: boolean
}) {
  return <section className="ticket-detail-fields">
    <h3>事项资料</h3>
    <Form.Item name={['localDetail', 'kind']} hidden initialValue={initializeDefaults ? kind : undefined} preserve={false}><Input /></Form.Item>
    {kind === 'reship_exchange' && <>
      <div className="form-grid">
        <Form.Item name={['localDetail', 'resolution']} label="处理诉求" initialValue={initializeDefaults ? 'reship' : undefined} rules={required} preserve={false}>
          <Radio.Group options={[{ value: 'reship', label: '补发' }, { value: 'exchange', label: '换货' }]} /></Form.Item>
        <Form.Item name={['localDetail', 'quantity']} label="申请数量" initialValue={initializeDefaults ? 1 : undefined} rules={required} preserve={false}><InputNumber min={1} max={999} precision={0} /></Form.Item>
        <Form.Item name={['localDetail', 'productName']} label="商品" preserve={false}><Input maxLength={200} /></Form.Item>
        <Form.Item name={['localDetail', 'sku']} label="货号" preserve={false}><Input maxLength={80} /></Form.Item>
      </div>
      <Form.Item name={['localDetail', 'reason']} label="补发换货原因" rules={textRequired} preserve={false}><Input.TextArea rows={2} maxLength={500} /></Form.Item>
    </>}
    {kind === 'offline_payment' && <>
      <div className="form-grid">
        <Form.Item name={['localDetail', 'paymentType']} label="申请类型" initialValue={initializeDefaults ? 'refund' : undefined} rules={required} preserve={false}>
          <Select options={[{ value: 'refund', label: '退款' }, { value: 'price_adjustment', label: '补差' }, { value: 'compensation', label: '补偿' }]} /></Form.Item>
        <Form.Item name={['localDetail', 'requestedAmount']} label="申请金额（元）" rules={required} preserve={false}>
          <InputNumber min={0} max={100000} precision={2} stringMode /></Form.Item>
      </div>
      <Form.Item name={['localDetail', 'reason']} label="申请原因" rules={textRequired} preserve={false}><Input.TextArea rows={2} maxLength={500} /></Form.Item>
    </>}
    {kind === 'logistics' && <>
      <div className="form-grid">
        <Form.Item name={['localDetail', 'issueType']} label="物流问题" initialValue={initializeDefaults ? 'tracking_query' : undefined} rules={required} preserve={false}>
          <Select options={[{ value: 'tracking_query', label: '物流查询' }, { value: 'stalled', label: '轨迹停滞' },
            { value: 'not_received', label: '签收未收到' }, { value: 'damaged', label: '运输破损' }, { value: 'address_review', label: '地址核对' }]} /></Form.Item>
        <Form.Item name={['localDetail', 'carrier']} label="快递公司" preserve={false}><Input maxLength={80} /></Form.Item>
      </div>
      <Form.Item name={['localDetail', 'trackingNo']} label="待核对物流号" preserve={false}><Input maxLength={80} /></Form.Item>
      <Form.Item name={['localDetail', 'reason']} label="物流问题描述" rules={textRequired} preserve={false}><Input.TextArea rows={2} maxLength={500} /></Form.Item>
    </>}
    {kind === 'adverse_reaction' && <>
      <Form.Item name={['localDetail', 'symptomDescription']} label="消费者不适自述" rules={textRequired} preserve={false}><Input.TextArea rows={2} maxLength={500} /></Form.Item>
      <div className="form-grid">
        <Form.Item name={['localDetail', 'affectedArea']} label="不适部位" preserve={false}><Input maxLength={80} /></Form.Item>
        <Form.Item name={['localDetail', 'onsetInterval']} label="出现时间" preserve={false}><Input maxLength={80} /></Form.Item>
        <Form.Item name={['localDetail', 'productBatchNo']} label="产品批次" preserve={false}><Input maxLength={80} /></Form.Item>
        <Form.Item name={['localDetail', 'stoppedUse']} label="是否停用" initialValue={initializeDefaults ? 'unknown' : undefined} rules={required} preserve={false}><Radio.Group options={yesNo} /></Form.Item>
        <Form.Item name={['localDetail', 'soughtMedicalCare']} label="是否就医" initialValue={initializeDefaults ? 'unknown' : undefined} rules={required} preserve={false}><Radio.Group options={yesNo} /></Form.Item>
      </div>
    </>}
    {kind === 'return_refund' && <>
      <div className="form-grid">
        <Form.Item name={['localDetail', 'requestType']} label="退货诉求" initialValue={initializeDefaults ? 'return_refund' : undefined} rules={required} preserve={false}>
          <Radio.Group options={[{ value: 'return_refund', label: '退货退款' }, { value: 'refund_only', label: '仅退款' }]} /></Form.Item>
        <Form.Item name={['localDetail', 'parcelType']} label="包裹类型" initialValue={initializeDefaults ? 'unknown' : undefined} rules={required} preserve={false}>
          <Select options={[{ value: 'original', label: '原单' }, { value: 'reship', label: '补发件' }, { value: 'unknown', label: '未知' }]} /></Form.Item>
      </div>
      <Form.Item name={['localDetail', 'returnReason']} label="退货原因" rules={textRequired} preserve={false}><Input.TextArea rows={2} maxLength={500} /></Form.Item>
    </>}
  </section>
}
