import { Table } from 'antd'
import type { UsageView } from '../../api/client'

const STAGES: Record<string, string> = { draft: '起草', verify: '核验', image: '图片', rewrite: '改写', breakpoint: '断点' }
const money = (value?: number | null) => (value == null ? '未配置价格' : `¥${value.toFixed(4)}`)
const rate = (value?: number | null) => (value == null ? '—' : `${Math.round(value * 100)}%`)
const count = (value: number) => value.toLocaleString('zh-CN')

/** 模型配置页“评测与成本”：真实调用与 Mock 调用分开统计。 */
export function UsagePanel({ usage }: { usage: UsageView }) {
  const live = usage.live
  return <section className="yt-usage" aria-label="评测与成本">
    <div className="yt-usage-kpis">
      <div aria-label="真实调用"><span>真实调用</span><strong>{count(live.calls)}</strong></div>
      <div aria-label="每条回复调用"><span>每条回复调用</span><strong>{live.callsPerReply ?? '—'}</strong></div>
      <div aria-label="输入 Token"><span>输入 Token</span><strong>{count(live.promptTokens)}</strong></div>
      <div aria-label="缓存命中率"><span>缓存命中率</span><strong>{rate(live.cacheHitRate)}</strong></div>
      <div aria-label="估算费用"><span>估算费用</span><strong>{money(live.estimatedCost)}</strong></div>
      <div aria-label="每条回复成本"><span>每条回复成本</span><strong>{money(live.costPerReply)}</strong></div>
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
    <Table size="small" pagination={false} rowKey="model" dataSource={live.byModel} columns={[
      { title: '模型', dataIndex: 'model' },
      { title: '调用', dataIndex: 'calls', align: 'right' },
      { title: '输入 Token', dataIndex: 'promptTokens', align: 'right', render: count },
      { title: '估算费用', dataIndex: 'estimatedCost', align: 'right', render: money },
    ]} />
  </section>
}
