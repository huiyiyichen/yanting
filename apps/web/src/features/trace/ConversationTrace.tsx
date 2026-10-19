import { ExportOutlined } from '@ant-design/icons'
import { Empty, Select, Skeleton } from 'antd'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { platformApi, type TraceDetailView, type TraceListView } from '../../api/client'
import { OrchestrationTree } from './OrchestrationTree'
import { SpanInspector } from './SpanInspector'
import { modelsOf } from './traceModel'

const STATUS: Record<string, string> = { sent: '已发送', handoff: '转人工', failed: '失败', running: '运行中', draft: '草稿', ok: '完成', stale: '已过期', interrupted: '中断' }
const hm = (iso: string) => new Date(Date.parse(iso) + 8 * 3600000).toISOString().slice(11, 16)

/** 接待插件「轨迹」页签（反馈 10-18 #3）：当前对话最新一轮的 Agent 编排（可切换轮次），复用编排卡片树紧凑版。 */
export function ConversationTrace({ conversationId, refreshKey }: { conversationId: string | null; refreshKey?: string | number | null }) {
  const [list, setList] = useState<TraceListView | null>(null)
  const [picked, setPicked] = useState<string | null>(null)
  const [detail, setDetail] = useState<TraceDetailView | null>(null)
  const [inspect, setInspect] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    if (!conversationId) { setList(null); return }
    platformApi.traces({ conversationId, limit: 12 }).then((data) => { if (live) setList(data) })
      .catch(() => { if (live) setList({ items: [], total: 0 }) })
    return () => { live = false }
  }, [conversationId, refreshKey])
  useEffect(() => { setPicked(null); setInspect(null) }, [conversationId])
  const items = list?.items ?? []
  const currentId = picked && items.some((t) => t.traceId === picked) ? picked : items[0]?.traceId ?? null
  useEffect(() => {
    let live = true
    if (!currentId) { setDetail(null); return }
    platformApi.trace(currentId).then((d) => { if (live) setDetail(d) }).catch(() => { if (live) setDetail(null) })
    return () => { live = false }
  }, [currentId, refreshKey])

  if (!list) return <Skeleton active paragraph={{ rows: 6 }} />
  if (!items.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="这段对话还没有 AI 编排记录" />
  const rounds = items.length
  return <div className="yt-ctrace" aria-label="对话编排">
    <div className="yt-ctrace-head">
      <Select size="small" value={currentId} onChange={setPicked} aria-label="切换轮次" popupMatchSelectWidth={false}
        options={items.map((t, i) => ({ value: t.traceId, label: `第 ${rounds - i} 轮 · ${hm(t.startedAt)} · ${STATUS[t.status] ?? t.status}${i === 0 ? '（最新）' : ''}` }))} />
      {currentId && <Link className="open" to={`/platform/models?tab=trace&trace=${encodeURIComponent(currentId)}`}>追踪台<ExportOutlined /></Link>}
    </div>
    {detail && detail.traceId === currentId
      ? <OrchestrationTree compact startedAt={detail.startedAt} spans={detail.spans} selected={inspect} onSelect={setInspect}
        trigger={detail.triggerText ?? null} outcome={detail.outcomeText ?? null} outcomeStatus={detail.status} />
      : <Skeleton active paragraph={{ rows: 6 }} />}
    <SpanInspector span={detail?.spans.find((s) => s.spanId === inspect) ?? null} models={detail ? modelsOf(detail.spans, inspect) : []} onClose={() => setInspect(null)} />
  </div>
}
