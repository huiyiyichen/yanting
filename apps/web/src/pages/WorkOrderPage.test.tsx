import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { TicketView } from '../api/client'
import { WorkOrderPage } from './WorkOrderPage'

const base: TicketView = {
  ticketId: 'LOCAL-A', title: '物流停滞跟进', conversationId: 'S00001', buyerAlias: '消费者甲',
  workOrderType: 'logistics', status: 'pending', priority: 'normal', assignee: 'G001',
  createdAt: '2026-10-02T04:00:00Z', updatedAt: '2026-10-02T04:00:00Z', revision: 1,
}
let rows: TicketView[]
let fetchMock: ReturnType<typeof vi.fn>
const json = (payload: unknown) => ({ ok: true, status: 200, text: async () => JSON.stringify(payload) }) as Response
const mount = (entry = '/platform/work-orders') => render(<ConfigProvider><MemoryRouter initialEntries={[entry]}><WorkOrderPage /></MemoryRouter></ConfigProvider>)

beforeEach(() => {
  localStorage.clear()
  rows = [base, { ...base, ticketId: 'LOCAL-B', title: '换货待确认', assignee: 'G002' }]
  fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/operators')) return json({
      defaultOperatorId: 'G001', operators: [{ operatorId: 'G001', name: '模拟客服 G001' }, { operatorId: 'G002', name: '模拟客服 G002' }],
    })
    if (path.endsWith('/reception/queue')) return json({
      items: [{ conversationId: 'S00001', buyerAlias: '消费者甲' }], unreadTotal: 0,
    })
    if (path.endsWith('/service-context')) return json({ conversationId: 'S00001', orders: [], products: [] })
    if (path.endsWith('/tickets') && options?.method === 'POST') {
      const payload = JSON.parse(String(options.body))
      const row = { ...base, ...payload, ticketId: 'LOCAL-C', events: [] }
      rows = [...rows, row]
      return json(row)
    }
    if (path.endsWith('/tickets')) return json(rows)
    if (path.includes('/tickets/') && options?.method === 'PUT') {
      const existing = rows.find((row) => path.endsWith(row.ticketId))!
      const payload = JSON.parse(String(options.body))
      const result = { ...existing, ...payload, revision: existing.revision + 1 }
      rows = rows.map((row) => row.ticketId === existing.ticketId ? result : row)
      return json(result)
    }
    if (path.includes('/tickets/')) return json(rows.find((row) => path.endsWith(row.ticketId)))
    throw new Error(`Unexpected request: ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => { localStorage.clear(); vi.unstubAllGlobals() })

const savedDetails: Array<{ detail: NonNullable<TicketView['localDetail']>; label: string; value: string }> = [
  { detail: { kind: 'reship_exchange', resolution: 'exchange', quantity: 3, productName: '核对商品', sku: 'SKU-A', reason: '错发待核对' },
    label: '补发换货原因', value: '错发待核对' },
  { detail: { kind: 'offline_payment', paymentType: 'price_adjustment', requestedAmount: '20.50', reason: '价保差额待核对' },
    label: '申请原因', value: '价保差额待核对' },
  { detail: { kind: 'logistics', issueType: 'stalled', carrier: '快递甲', trackingNo: 'TRACK-A', reason: '已有物流停滞记录' },
    label: '物流问题描述', value: '已有物流停滞记录' },
  { detail: { kind: 'adverse_reaction', symptomDescription: '消费者自述泛红', affectedArea: '面部', onsetInterval: '使用后', productBatchNo: 'BATCH-A',
    stoppedUse: 'yes', soughtMedicalCare: 'no' }, label: '消费者不适自述', value: '消费者自述泛红' },
  { detail: { kind: 'return_refund', requestType: 'refund_only', parcelType: 'reship', returnReason: '退货资料待核对' },
    label: '退货原因', value: '退货资料待核对' },
]

it.each(savedDetails)('已有 $detail.kind 资料回填并原样保存，不被默认值覆盖', async ({ detail, label, value }) => {
  const user = userEvent.setup()
  rows = [{ ...base, workOrderType: detail.kind, localDetail: detail }]
  mount('/platform/work-orders?ticket=LOCAL-A')
  const field = await screen.findByLabelText(label)
  expect(field).toHaveValue(value)
  await user.type(screen.getByLabelText('跟进记录'), '核对本地资料，未执行真实售后')
  await user.click(screen.getByRole('button', { name: /保存跟进/ }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(true))
  const [, options] = fetchMock.mock.calls.find(([, options]) => options?.method === 'PUT')!
  expect(JSON.parse(String(options?.body)).localDetail).toEqual(detail)
}, 15000)

it('切换工单重新初始化专属资料，不保留前一张工单的修改', async () => {
  const user = userEvent.setup()
  rows = [
    { ...base, localDetail: savedDetails[2].detail },
    { ...base, ticketId: 'LOCAL-B', title: '退货核对', workOrderType: 'return_refund', localDetail: savedDetails[4].detail },
  ]
  mount()
  await user.click(await screen.findByRole('button', { name: /物流停滞跟进.*LOCAL-A/ }))
  await user.type(await screen.findByLabelText('物流问题描述'), '未保存内容')
  await user.click(screen.getByRole('button', { name: /关闭|Close/ }))
  await user.click(await screen.findByRole('button', { name: /退货核对.*LOCAL-B/ }))
  expect(await screen.findByLabelText('退货原因')).toHaveValue('退货资料待核对')
  expect(screen.queryByLabelText('物流问题描述')).not.toBeInTheDocument()
}, 15000)

it('无本地资料的源工单仅跟进时不提交隐藏的默认资料', async () => {
  const user = userEvent.setup()
  rows = [{ ...base, sourceRecordId: 'source-A', detail: { issueType: '历史源问题' } }]
  mount('/platform/work-orders?ticket=LOCAL-A')
  await user.type(await screen.findByLabelText('跟进记录'), '仅跟进，不修改来源')
  await user.click(screen.getByRole('button', { name: /保存跟进/ }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(true))
  const [, options] = fetchMock.mock.calls.find(([, options]) => options?.method === 'PUT')!
  expect(JSON.parse(String(options?.body)).localDetail).toBeUndefined()
}, 15000)

it('我的待办随显式模拟客服身份切换', async () => {
  const user = userEvent.setup()
  mount()
  await screen.findByText('物流停滞跟进')
  await user.click(screen.getByRole('tab', { name: '我的待办' }))
  expect(screen.queryByText('换货待确认')).not.toBeInTheDocument()
  await user.click(screen.getByRole('combobox', { name: '模拟客服' }))
  await user.click(await screen.findByText('模拟客服 G002', { selector: '.ant-select-item-option-content' }))
  await screen.findByText('换货待确认')
  expect(screen.queryByText('物流停滞跟进')).not.toBeInTheDocument()
  expect(localStorage.getItem('service-desk.demo-operator')).toBe('G002')
})

it('类型切换清除旧字段并将结构化资料和操作身份提交后端', async () => {
  const user = userEvent.setup()
  mount()
  await screen.findByText('物流停滞跟进')
  await user.click(screen.getByRole('combobox', { name: '模拟客服' }))
  await user.click(await screen.findByText('模拟客服 G002', { selector: '.ant-select-item-option-content' }))
  await user.click(screen.getByRole('button', { name: '新建工单' }))
  const dialog = within(screen.getByRole('dialog'))
  await user.type(dialog.getByLabelText('事项'), '价保待核对')
  await user.click(dialog.getByLabelText('客户会话'))
  await user.click(await screen.findByText('消费者甲 · S00001', { selector: '.ant-select-item-option-content' }))
  await user.type(dialog.getByLabelText('待核对物流号'), 'OLD-TRACKING')
  await user.click(dialog.getByLabelText('工单类型'))
  await user.click(await screen.findByText('线下打款', { selector: '.ant-select-item-option-content' }))
  expect(dialog.queryByLabelText('待核对物流号')).not.toBeInTheDocument()
  await user.type(dialog.getByLabelText('申请金额（元）'), '20.50')
  await user.type(dialog.getByLabelText('申请原因'), '核对价保差额')
  await user.type(dialog.getByLabelText('事项说明'), '待人工核对，未执行打款')
  await user.click(dialog.getByRole('button', { name: /创\s*建/ }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) =>
    String(url).endsWith('/tickets') && options?.method === 'POST')).toBe(true))
  const [, options] = fetchMock.mock.calls.find(([url, options]) =>
    String(url).endsWith('/tickets') && options?.method === 'POST')!
  const payload = JSON.parse(String(options?.body))
  expect(payload.assignee).toBe('G002')
  expect(payload.localDetail.kind).toBe('offline_payment')
  expect(Number(payload.localDetail.requestedAmount)).toBe(20.5)
  expect(payload.localDetail.reason).toBe('核对价保差额')
  expect(payload.localDetail.trackingNo).toBeUndefined()
  expect(options?.headers).toEqual(expect.objectContaining({ 'X-Demo-Operator': 'G002' }))
}, 30000)

it('默认物流资料直接创建时保留类型和默认选项', async () => {
  const user = userEvent.setup()
  mount()
  await screen.findByText('物流停滞跟进')
  await user.click(screen.getByRole('button', { name: '新建工单' }))
  const dialog = within(screen.getByRole('dialog'))
  await user.type(dialog.getByLabelText('事项'), '物流资料核对')
  await user.click(dialog.getByLabelText('客户会话'))
  await user.click(await screen.findByText('消费者甲 · S00001', { selector: '.ant-select-item-option-content' }))
  await user.type(dialog.getByLabelText('物流问题描述'), '消费者咨询已有物流')
  await user.type(dialog.getByLabelText('事项说明'), '本地核对')
  await user.click(dialog.getByRole('button', { name: /创\s*建/ }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, options]) =>
    String(url).endsWith('/tickets') && options?.method === 'POST')).toBe(true))
  const [, options] = fetchMock.mock.calls.find(([url, options]) =>
    String(url).endsWith('/tickets') && options?.method === 'POST')!
  expect(JSON.parse(String(options?.body)).localDetail).toEqual({
    kind: 'logistics', issueType: 'tracking_query', reason: '消费者咨询已有物流',
  })
}, 15000)

it('取消后重开新建窗口保留默认类型选项并清除未保存字段', async () => {
  const user = userEvent.setup()
  mount()
  await screen.findByText('物流停滞跟进')
  await user.click(screen.getByRole('button', { name: '新建工单' }))
  let dialog = within(screen.getByRole('dialog'))
  await user.type(dialog.getByLabelText('事项'), '取消的草稿')
  await user.type(dialog.getByLabelText('待核对物流号'), 'OLD-TRACKING')
  await user.click(dialog.getByRole('button', { name: /取\s*消/ }))
  await user.click(screen.getByRole('button', { name: '新建工单' }))
  dialog = within(screen.getByRole('dialog'))
  expect(dialog.getByLabelText('事项')).toHaveValue('')
  expect(dialog.getByLabelText('待核对物流号')).toHaveValue('')
  expect(dialog.getByText('物流查询')).toBeInTheDocument()
  await user.type(dialog.getByLabelText('事项'), '重开后物流核对')
  await user.click(dialog.getByLabelText('客户会话'))
  await user.click(await screen.findByText('消费者甲 · S00001', { selector: '.ant-select-item-option-content' }))
  await user.type(dialog.getByLabelText('物流问题描述'), '重开后核对')
  await user.type(dialog.getByLabelText('事项说明'), '未执行物流操作')
  await user.click(dialog.getByRole('button', { name: /创\s*建/ }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(true))
  const [, options] = fetchMock.mock.calls.find(([, options]) => options?.method === 'POST')!
  expect(JSON.parse(String(options?.body)).localDetail).toEqual({
    kind: 'logistics', issueType: 'tracking_query', reason: '重开后核对',
  })
}, 15000)

it('到期待办过滤已完成工单并按期限先后排列', async () => {
  const user = userEvent.setup()
  rows = [
    { ...base, title: '晚到期', dueAt: '2000-01-02T00:00:00Z' },
    { ...base, ticketId: 'LOCAL-B', title: '早到期', dueAt: '2000-01-01T00:00:00Z' },
    { ...base, ticketId: 'LOCAL-C', title: '已处理完', status: 'resolved', dueAt: '2000-01-01T00:00:00Z' },
  ]
  mount()
  await screen.findByText('晚到期')
  await user.click(screen.getByRole('tab', { name: '已到期' }))
  expect(screen.queryByText('已处理完')).not.toBeInTheDocument()
  const titles = screen.getAllByRole('button').filter((button) => button.classList.contains('table-title-link'))
  expect(titles.map((button) => button.textContent)).toEqual(['早到期LOCAL-B', '晚到期LOCAL-A'])
})
