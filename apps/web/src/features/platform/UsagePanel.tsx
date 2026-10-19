import { Table } from 'antd'
import type { UsageView } from '../../api/client'

import { AGENT_LABEL } from '../trace/traceModel'

const STAGES: Record<string, string> = { draft: '起草', verify: '核验', image: '图片', rewrite: '改写', breakpoint: '断点', other: '其他' }
const modelName = (value: string) => (!value || value === 'unknown' ? '未识别模型' : value)
const money = (value?: number | null) => (value == null ? '—' : `¥${value.toFixed(4)}`)
const rate = (value?: number | null) => (value == null ? '—' : `${Math.round(value * 100)}%`)
const count = (value: number) => value.toLocaleString('zh-CN')

/** 模型配置页“评测与成本”：真实调用与 Mock 调用分开统计。 */
export function UsagePanel({ usage, onOpenTrace }: { usage: UsageView; onOpenTrace?: (traceId: string) => void }) {
  const live = usage.live
  // 有真实调用时按真实数据分 Agent；只有 Mock 时也给出结构（标注 Mock），便于演示多 Agent 的成本分布
  const agentSource = live.byAgent?.length ? 'live' : usage.mock.byAgent?.length ? 'mock' : null
  const agents = agentSource === 'live' ? live.byAgent : agentSource === 'mock' ? usage.mock.byAgent : []
  return <section className="yt-usage" aria-label="评测与成本">
    <div className="yt-usage-kpis is-main">
      <div aria-label="每条回复成本"><span>每条回复成本</span><strong>{money(live.costPerReply)}</strong></div>
      <div aria-label="缓存命中率"><span>缓存命中率</span><strong>{rate(live.cacheHitRate)}</strong></div>
      <div aria-label="每条回复调用"><span>每条回复调用</span><strong>{live.callsPerReply ?? '—'}</strong></div>
    </div>
    <div className="yt-usage-kpis is-minor">
      <div aria-label="真实调用"><span>真实调用</span><strong>{count(live.calls)}</strong></div>
      <div aria-label="输入 Token"><span>输入 Token</span><strong>{count(live.promptTokens)}</strong></div>
      <div aria-label="估算费用"><span>估算费用</span><strong>{money(live.estimatedCost)}</strong></div>
      <div aria-label="Mock 调用"><span>Mock 调用</span><strong>{count(usage.mock.calls)}</strong></div>
    </div>
    <Table size="small" pagination={false} rowKey="stage" dataSource={live.byStage} columns={[
      { title: '节点', dataIndex: 'stage', render: (value: string) => STAGES[value] ?? value },
      { title: '调用', dataIndex: 'calls', align: 'right' },
      { title: '输入 Token', dataIndex: 'promptTokens', align: 'right', render: count },
      { title: '缓存命中', dataIndex: 'cachedTokens', align: 'right', render: count },
      { title: '输出 Token', dataIndex: 'completionTokens', align: 'right', render: count },
      { title: '耗时（秒）', dataIndex: 'latencySeconds', align: 'right' },
    ]} />
    {agents.length > 0 && <Table size="small" pagination={false} rowKey="agent" dataSource={agents} aria-label="按 Agent"
      title={() => `按 Agent${agentSource === 'mock' ? '（Mock 调用）' : ''}`} columns={[
        { title: 'Agent', dataIndex: 'agent', render: (value: string) => AGENT_LABEL[value] ?? (value === 'other' ? '其他' : value) },
        { title: '调用', dataIndex: 'calls', align: 'right' },
        { title: '输入 Token', dataIndex: 'promptTokens', align: 'right', render: count },
        { title: '输出 Token', dataIndex: 'completionTokens', align: 'right', render: count },
        { title: '估算费用', dataIndex: 'estimatedCost', align: 'right', render: money },
        { title: '追踪', dataIndex: 'latestTraceId', align: 'right', render: (id: string | null, row) =>
          id && onOpenTrace ? <a onClick={() => onOpenTrace(id)} aria-label={`查看${AGENT_LABEL[row.agent] ?? row.agent}最近追踪`}>最近一次</a> : '—' },
      ]} />}
    <Table size="small" pagination={false} rowKey="model" dataSource={live.byModel} columns={[
      { title: '模型', dataIndex: 'model', render: modelName },
      { title: '调用', dataIndex: 'calls', align: 'right' },
      { title: '输入 Token', dataIndex: 'promptTokens', align: 'right', render: count },
      { title: '估算费用', dataIndex: 'estimatedCost', align: 'right', render: money },
    ]} />
  </section>
}
