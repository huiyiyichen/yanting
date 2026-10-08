import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'

const item = {
  conversationId: 'live-1', buyerAlias: '消费者甲', title: '商品咨询', preview: '收到商品包装破损',
  updatedAt: '2026-10-01T08:00:00', dataSource: 'live', messageRevision: 1, unreadCount: 1,
  serviceMode: 'operator_assisted', modeRevision: 1, autoReplyStatus: 'idle',
}
const context = {
  datasetId: 'loreal-official-mock', batchId: 'batch-1', conversationId: 'live-1',
  buyerAlias: '消费者甲', buyerAliases: ['消费者甲'], orders: [], workOrders: [], timeline: [],
  products: [{ sku: 'SKU01', name: '测试轻透粉底液30ml', unitPriceMinor: 25900, sourceRecordIds: ['src-1'] }],
  serviceNodes: [{ occurredAt: '2026-05-01T08:00:00', kind: '工单创建', title: 'BH001', sourceRecordId: 'src-1' }],
  historyConversationIds: ['S00002'],
  historyServices: [{
    conversationId: 'S00002', firstAt: '2026-04-30T08:00:00Z', lastAt: '2026-04-30T09:00:00Z',
    latestCustomerMessage: '上次咨询过包装破损怎么处理。',
    latestStaffMessage: '客服曾回复：我先帮您核对换货记录。',
    orderIds: ['O-OLD'], workOrderIds: ['BH-OLD'], relation: 'historical', sameTopic: true,
  }],
}
const assistant = {
  observationId: 'obs-1', datasetId: 'loreal-official-mock', batchId: 'batch-1',
  conversationId: 'live-1', currentQuestion: '包装破损', serviceSummary: '核对破损换货工单',
  emotionLevel: 'dissatisfied', emotionTrend: 'rising', riskTypes: ['unknown'], riskLevel: 'unknown',
  riskStatus: 'pending', riskReason: '', evidenceRefs: [], missingInformation: [], nextSteps: ['核对工单'],
  replySuggestions: [{
    style: 'recommended', body: '我来核对这笔订单的换货记录。',
    empathyDimensions: [
      { key: 'emotion_response', label: '情绪回应', status: 'present', reason: '已承接' },
      { key: 'business_handling', label: '业务处理', status: 'present', reason: '已说明' },
      { key: 'personalized', label: '个性化', status: 'missing', reason: '未引用' },
    ],
  }],
  inputHash: 'hash-1', stale: false, isMock: true, modelId: 'test', promptVersion: 'LOREAL_ASSISTANT@1',
  knowledgeStatus: 'sufficient', knowledgeEvidence: [
    { chunk_id: 'loreal-service', document_title: '消费者服务事实与处理边界', quoted_excerpt: '待审核不等于转账成功。' },
  ],
  verificationStatus: 'verified', memoryItems: [], workflowSteps: [], modelUsage: { calls: 2 },
}

let fetchMock: ReturnType<typeof vi.fn>
let generated = false
function json(payload: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(payload) } as Response
}
function renderApp(path = '/support') {
  return render(<ConfigProvider><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></ConfigProvider>)
}
beforeEach(() => {
  generated = false
  localStorage.removeItem('service-desk.demo-operator')
  fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/desk/operators')) return json({
      defaultOperatorId: 'G001', operators: [{ operatorId: 'G001', name: '模拟客服 G001' }],
    })
    if (path.endsWith('/reception/queue')) return json({ items: [item], unreadTotal: 1 })
    if (path.endsWith('/service-context')) return json(context)
    if (path.endsWith('/memory')) return json({ conversationId: 'live-1', revision: 0, items: [], sources: [], stale: false, verified: false })
    if (path.endsWith('/assistant')) {
      if (options?.method === 'POST') generated = true
      return json(generated ? assistant : null)
    }
    if (path.endsWith('/messages')) return json([])
    if (path.endsWith('/work-orders/all')) return json([{
      sourceRecordId: 'src-1', workOrderId: 'BH001', workOrderType: 'reship_exchange',
      conversationId: 'live-1', buyerAlias: '消费者甲', sourceStatus: '进行中',
      normalizedStatus: 'in_progress', createdAt: '2026-05-01T08:00:00', detail: { productName: '测试粉底液' },
    }])
    if (path.includes('/risk-alerts')) return json([])
    if (path.includes('/desk/risks') || /\/desk\/conversations\/[^/]+\/risks$/.test(path)) return json([])
    if (path.includes('/desk/tickets')) return json([{
      ticketId: 'BH001', title: '破损换货', workOrderType: 'reship_exchange',
      conversationId: 'live-1', buyerAlias: '消费者甲', sourceStatus: '进行中',
      status: 'pending', priority: 'normal', assignee: '', revision: 0,
      createdAt: '2026-05-01T08:00:00', updatedAt: '2026-05-01T08:00:00', events: [], detail: {},
    }])
    if (path.includes('/customer/conversations')) return json([])
    if (path.endsWith('/onboarding')) return json({ greeting: '', quickReplies: [] })
    return json({ ok: true })
  })
  vi.stubGlobal('fetch', fetchMock)
})
afterEach(() => vi.unstubAllGlobals())

describe('颜听工作台', () => {
  it.each(['customer', 'support'])('%s 输入框支持回车发送与 Shift+Enter 换行', async (role) => {
    const user = userEvent.setup()
    const original = fetchMock.getMockImplementation() as
      (input: RequestInfo | URL, options?: RequestInit) => Promise<Response>
    fetchMock.mockImplementation(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).includes('/customer/conversations?')) return json([{
        conversationId: 'live-1', title: '商品咨询', customerId: 'CUST-DEMO-01',
        serviceMode: 'operator_assisted', messageRevision: 1, modeRevision: 1,
      }])
      return original(input, options)
    })
    renderApp(`/${role}`)
    const input = await screen.findByLabelText(role === 'customer' ? '客户消息输入框' : '客服回复输入框')
    await waitFor(() => expect(input).toBeEnabled())
    await user.type(input, '亲，收到啦')
    fireEvent.compositionStart(input)
    fireEvent.keyDown(input, { key: 'Enter' })
    fireEvent.compositionEnd(input)
    await user.keyboard('{Shift>}{Enter}{/Shift}')
    expect(input).toHaveValue('亲，收到啦\n')
    expect(fetchMock.mock.calls.filter(([url, options]) => String(url).endsWith('/messages')
      && options?.method === 'POST')).toHaveLength(0)
    await user.keyboard('{Enter}')
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url, options]) =>
      String(url).endsWith('/messages') && options?.method === 'POST')).toHaveLength(1))
  })
  it.each(['customer', 'support'])('%s 输入框支持图片粘贴预览和单独发送', async (role) => {
    const original = fetchMock.getMockImplementation() as
      (input: RequestInfo | URL, options?: RequestInit) => Promise<Response>
    fetchMock.mockImplementation(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).includes('/customer/conversations?')) return json([{
        conversationId: 'live-1', title: '商品咨询', customerId: 'CUST-DEMO-01',
        serviceMode: 'operator_assisted', messageRevision: 1, modeRevision: 1,
      }])
      if (String(input).endsWith('/attachments')) return json({
        attachmentId: 'att-product', conversationId: 'live-1',
        mimeType: 'image/png', byteSize: 100, width: 20, height: 20,
      })
      return original(input, options)
    })
    renderApp(`/${role}`)
    const input = await screen.findByLabelText(role === 'customer' ? '客户消息输入框' : '客服回复输入框')
    await waitFor(() => expect(input).toBeEnabled())
    const file = new File(['image'], '商品.png', { type: 'image/png' })
    fireEvent.paste(input, { clipboardData: { files: [file], getData: () => '' } })
    await waitFor(() => expect(screen.getByRole('button', { name: '发送' })).toBeEnabled())
    expect(fetchMock.mock.calls.find(([path]) => String(path).endsWith('/attachments'))?.[1]?.body).toBeInstanceOf(FormData)
    expect((await screen.findAllByRole('img', { name: '商品.png' })).length).toBeGreaterThan(0)
    fireEvent.keyDown(input, { key: 'Enter' })
    await waitFor(() => {
      const send = fetchMock.mock.calls.find(([url, options]) => String(url).endsWith('/messages')
        && options?.method === 'POST')
      expect(JSON.parse(send?.[1]?.body as string)).toMatchObject({
        body: '', attachmentIds: ['att-product'],
      })
    })
  }, 15000)
  it('保留管理导航并移除 JEV', async () => {
    renderApp()
    expect(screen.queryByText(/JEV/)).not.toBeInTheDocument()
    for (const name of ['客户视角', '客服工作台', '风险预警', '模型配置', '知识库', 'Prompt 管理', '工单管理']) {
      expect(screen.getByRole('link', { name })).toBeInTheDocument()
    }
    await screen.findByRole('button', { name: '消费者甲 live-1' })
  })
  it('队列显示真实最新消息和未读，不依赖模型', async () => {
    renderApp()
    expect(await screen.findByText(/收到商品包装破损/)).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: '全部' })).toBeChecked()
    expect(fetchMock.mock.calls.some(([path, options]) => String(path).endsWith('/assistant') && options?.method === 'POST')).toBe(false)
    expect(screen.getByRole('button', { name: '刷新会话' })).toBeInTheDocument()
  })
  it('队列短暂失联恢复后清除错误并回读会话，不要求重新打开页面', async () => {
    const original = fetchMock.getMockImplementation() as
      (input: RequestInfo | URL, options?: RequestInit) => Promise<Response>
    let reads = 0
    fetchMock.mockImplementation(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith('/reception/queue') && reads++ === 0) {
        return json({ error: { code: 'query_failed', message: '队列暂时失联' } }, 500)
      }
      return original(input, options)
    })
    renderApp('/support?conversation=live-1')
    expect(await screen.findByText('队列暂时失联')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('队列暂时失联')).not.toBeInTheDocument(), { timeout: 4000 })
    expect(await screen.findByRole('button', { name: '消费者甲 live-1' })).toBeInTheDocument()
  })
  it('风险链接独立于会话按钮并携带类型跳转', async () => {
    const user = userEvent.setup()
    const original = fetchMock.getMockImplementation() as
      (input: RequestInfo | URL, options?: RequestInit) => Promise<Response>
    fetchMock.mockImplementation(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith('/reception/queue')) return json({
        items: [{ ...item, currentEmotion: 'calm', activeRiskTypes: [],
          reviewRiskTypes: ['complaint_risk'] }], unreadTotal: 1,
      })
      return original(input, options)
    })
    renderApp()
    const link = await screen.findByRole('link', { name: '复核投诉风险 · 消费者甲' })
    expect(link.closest('button')).toBeNull()
    expect(link).toHaveAttribute('href', '/risk?conversation=live-1&type=complaint_risk')
    expect(await screen.findByRole('link', { name: '复核当前投诉风险' })).toHaveAttribute(
      'href', '/risk?conversation=live-1&type=complaint_risk',
    )
    await user.click(link)
    expect(await screen.findByRole('heading', { name: '风险预警' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([path, options]) =>
      String(path).endsWith('/assistant') && options?.method === 'POST')).toBe(false)
  }, 15000)
  it('插件独立展示当前风险动作，不需要生成AI回复', async () => {
    const original = fetchMock.getMockImplementation() as
      (input: RequestInfo | URL, options?: RequestInit) => Promise<Response>
    fetchMock.mockImplementation(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith('/desk/conversations/live-1/risks')) return json([{
        incidentId: 'incident-live-1', conversationIds: ['live-1'], orderIds: [],
        riskStatus: 'pending', attentionState: 'active', currentAction: 'intervene', serviceState: 'live',
        signals: [{ alertId: 'wait-1', conversationId: 'live-1', riskType: 'response_wait', riskStatus: 'pending',
          riskLevel: 'medium', signalActive: true, triggerSummary: '当前消费者等待超过120秒',
          recommendedAction: '优先回复消费者当前问题' }],
      }])
      return original(input, options)
    })
    renderApp()
    expect(await screen.findByText('当前消费者等待超过120秒')).toBeInTheDocument()
    expect(screen.getByText('优先回复消费者当前问题')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([path, options]) =>
      String(path).endsWith('/assistant') && options?.method === 'POST')).toBe(false)
  }, 15000)
  it('插件风险查询失败不阻断聊天与已有AI草稿', async () => {
    const original = fetchMock.getMockImplementation() as
      (input: RequestInfo | URL, options?: RequestInit) => Promise<Response>
    fetchMock.mockImplementation(async (input: RequestInfo | URL, options?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/desk/conversations/live-1/risks')) return json({
        error: { code: 'query_failed', message: '风险服务暂不可用' },
      }, 500)
      if (path.endsWith('/messages')) return json([{
        messageId: 'customer-1', conversationId: 'live-1', senderRole: 'customer',
        body: '聊天内容正常保留', messageRevision: 1, createdAt: '2026-10-03T01:00:00Z',
      }])
      if (path.endsWith('/assistant')) return json(assistant)
      return original(input, options)
    })
    renderApp()
    expect(await screen.findByText('风险读取失败：风险服务暂不可用')).toBeInTheDocument()
    expect(await screen.findByText('聊天内容正常保留')).toBeInTheDocument()
    expect(await screen.findByText('我来核对这笔订单的换货记录。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /采\s*用/ })).toBeEnabled()
    expect(fetchMock.mock.calls.some(([path, options]) =>
      String(path).endsWith('/assistant') && options?.method === 'POST')).toBe(false)
  }, 15000)
  it('生成建议是独立操作，采用只写草稿', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByRole('button', { name: '消费者甲 live-1' })
    await waitFor(() => expect(screen.getByRole('button', { name: /生成建议/ })).toBeEnabled())
    await user.click(screen.getByRole('button', { name: /生成建议/ }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([path, options]) =>
      String(path).endsWith('/assistant') && options?.method === 'POST')).toBe(true))
    await screen.findByText('我来核对这笔订单的换货记录。')
    await user.click(screen.getByRole('button', { name: /采\s*用/ }))
    expect(fetchMock.mock.calls.some(([path, options]) => String(path).endsWith('/messages') && options?.method === 'POST')).toBe(false)
  }, 15000)
  it('个性化建议显示方案理由和逐字证据，不隐式调用生成', async () => {
    const user = userEvent.setup()
    const original = fetchMock.getMockImplementation() as
      ((input: RequestInfo | URL, options?: RequestInit) => Promise<Response>) | undefined
    fetchMock.mockImplementation(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith('/assistant')) return json({
        ...assistant,
        personalizedAdvice: [{
          category: 'routine', title: '按当前分区护理', scope: 'general_consumer',
          productName: '巴黎欧莱雅黑胖子气垫 200 中性象牙白',
          action: '油性区域避免过度清洁。', rationale: '匹配你当前T区出油的困扰。',
          evidence: [
            { sourceRef: 'm1', label: '消费者自述', quote: 'T区出油', kind: 'customer_message' },
            { sourceRef: 'k1', label: '通用护理资料', quote: '油性区域温和清洁', kind: 'knowledge' },
          ],
        }],
      })
      return original?.(input, options)
    })
    renderApp()
    await user.click(await screen.findByText('更多信息'))
    expect(await screen.findByText('个性化建议')).toBeInTheDocument()
    expect(screen.getByText('巴黎欧莱雅黑胖子气垫 200 中性象牙白')).toBeInTheDocument()
    expect(screen.getByText('油性区域避免过度清洁。')).toBeInTheDocument()
    expect(screen.getByText('匹配你当前T区出油的困扰。')).toBeInTheDocument()
    expect(screen.getByText('T区出油')).toBeInTheDocument()
    expect(screen.getByText('油性区域温和清洁')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([path, options]) =>
      String(path).endsWith('/assistant') && options?.method === 'POST')).toBe(false)
  })
  it('回复建议显示可解释的共情维度标签', async () => {
    const user = userEvent.setup()
    renderApp()
    await user.click(await screen.findByRole('button', { name: /生成建议/ }))
    expect(await screen.findByText('情绪回应')).toBeInTheDocument()
    expect(screen.getByText('业务处理')).toBeInTheDocument()
    expect(screen.getByText('个性化')).toBeInTheDocument()
  })
  it('客服先看到跨会话消费者服务档案', async () => {
    renderApp()
    expect(await screen.findByRole('heading', { name: '消费者服务档案' })).toBeInTheDocument()
    expect(screen.getByText('1 次历史进线')).toBeInTheDocument()
    expect(screen.getByText('上次咨询过包装破损怎么处理。')).toBeInTheDocument()
    expect(screen.getByText('同一诉求')).toBeInTheDocument()
  })
  it('没有模型缓存的官方会话先展示交接内容，摘要和建议位于风险之前', async () => {
    const original = fetchMock.getMockImplementation() as
      (input: RequestInfo | URL, options?: RequestInit) => Promise<Response>
    fetchMock.mockImplementation(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith('/messages')) return json([
        { messageId: 'm1', senderRole: 'customer', body: '退货已经寄回了，怎么还没退款？', messageRevision: 1 },
        { messageId: 'm2', senderRole: 'operator', body: '退货已收到，退款还在审核中。', messageRevision: 2 },
        { messageId: 'm3', senderRole: 'customer', body: '好的，谢谢。', messageRevision: 3 },
      ])
      return original(input, options)
    })
    renderApp()
    const brief = await screen.findByRole('region', { name: '交接摘要' })
    await waitFor(() => expect(brief).toHaveTextContent('客户最新反馈：好的，谢谢。'))
    expect(brief).toHaveTextContent('最初咨询：退货已经寄回了，怎么还没退款？')
    expect(brief).toHaveTextContent('客服曾回复：退货已收到，退款还在审核中。')
    const headings = screen.getAllByRole('heading', { level: 3 }).map((node) => node.textContent)
    expect(headings.slice(0, 3)).toEqual(['交接摘要', '回复建议', '风险关注'])
    expect(fetchMock.mock.calls.some(([path, options]) =>
      String(path).endsWith('/assistant') && options?.method === 'POST')).toBe(false)
  })
  it('图片可见信息有原图入口，不与商品知识或业务执行结果混在一起', async () => {
    const user = userEvent.setup()
    const original = fetchMock.getMockImplementation() as
      (input: RequestInfo | URL, options?: RequestInit) => Promise<Response>
    fetchMock.mockImplementation(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith('/assistant')) return json({
        ...assistant, groundingSources: [{
          sourceId: 'image:att-1', kind: 'image_observation', subjectId: 'live-1',
          label: '图片可见信息', text: '图中文字：2604B', fields: { attachmentId: 'att-1' },
        }],
      })
      return original(input, options)
    })
    renderApp()
    await user.click(await screen.findByText('更多信息'))
    expect(await screen.findByRole('heading', { name: '图片可见信息' })).toBeInTheDocument()
    expect(screen.getByText('图中文字：2604B')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看原图' })).toHaveAttribute(
      'href', '/api/customer/attachments/att-1/content',
    )
    expect(fetchMock.mock.calls.some(([path, options]) =>
      String(path).endsWith('/assistant') && options?.method === 'POST')).toBe(false)
  })
  it('新会话自动进入队列并提示新消息', async () => {
    let arrived = false
    const original = fetchMock.getMockImplementation() as
      ((input: RequestInfo | URL, options?: RequestInit) => Promise<Response>) | undefined
    fetchMock.mockImplementation(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith('/reception/queue') && arrived) return json({
        items: [{ ...item, conversationId: 'live-2', buyerAlias: '消费者乙', messageRevision: 2, unreadCount: 1 }, item],
        unreadTotal: 2,
      })
      return original?.(input, options)
    })
    renderApp()
    await screen.findByRole('button', { name: '消费者甲 live-1' })
    arrived = true
    expect(await screen.findByRole('button', { name: '消费者乙 live-2' }, { timeout: 3000 })).toBeInTheDocument()
    expect(await screen.findByText('新消息 · 消费者乙')).toBeInTheDocument()
  }, 15000)
  it('商品信息来自服务上下文', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByRole('button', { name: '消费者甲 live-1' })
    await user.click(screen.getByRole('tab', { name: '订单 0' }))
    expect(await screen.findByText('测试轻透粉底液30ml')).toBeInTheDocument()
    expect(screen.getByText('SKU01')).toBeInTheDocument()
    expect(screen.getByText('¥259.00')).toBeInTheDocument()
  })
  it('服务轨迹展示业务节点而非聊天原文', async () => {
    const user = userEvent.setup()
    renderApp()
    await screen.findByRole('button', { name: '消费者甲 live-1' })
    await user.click(screen.getByRole('tab', { name: '轨迹' }))
    expect(await screen.findByText('工单创建')).toBeInTheDocument()
    expect(screen.getByText('BH001')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })
  it('工单页显示源工单类型而非会话案件', async () => {
    renderApp('/platform/work-orders')
    expect(await screen.findByText('BH001')).toBeInTheDocument()
    expect(screen.queryByText('AI 托管')).not.toBeInTheDocument()
    expect(screen.queryByText('风险等级')).not.toBeInTheDocument()
  })
  it('客户页不加载内部辅助数据', async () => {
    renderApp('/customer')
    await screen.findByLabelText('客户消息输入框')
    expect(screen.queryByRole('tab', { name: '接待辅助' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: '知识依据' })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.every(([path]) => !String(path).includes('/support/'))).toBe(true)
    expect(screen.queryByText(/您可以先问这些/)).not.toBeInTheDocument()
  })
  it('请求失败提供真实错误，不伪装成空列表', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ error: { message: '连接失败' } }, 503)))
    renderApp()
    expect(await screen.findByText('连接失败')).toBeInTheDocument()
  })
})
