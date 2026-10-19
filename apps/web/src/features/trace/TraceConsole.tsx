import { CaretRightOutlined, DownloadOutlined, PauseOutlined } from '@ant-design/icons'
import { Button, Checkbox, Input, Segmented, Select } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { platformApi, type TraceDetailView, type TraceListView } from '../../api/client'
import { CitationChain } from './CitationChain'
import { OrchestrationTree } from './OrchestrationTree'
import { SpanInspector } from './SpanInspector'
import { buildLanes, modelsOf, replayFrames } from './traceModel'

const STATUS: Record<string, string> = { sent: '已发送', handoff: '转人工', failed: '失败', running: '运行中', ok: '完成', stale: '已过期' }
const hm = (iso: string) => new Date(Date.parse(iso) + 8 * 3600000).toISOString().slice(5, 16).replace('T', ' ').replace('-', '/')
const secs = (a: string, b?: string | null) => (b ? `${((Date.parse(b) - Date.parse(a)) / 1000).toFixed(1)}s` : '')

/** Agent 追踪台（模型配置页签）：筛选、列表、编排卡片树（主视图，含耗时）与引用链、节点检查器、回放、导出。 */
export function TraceConsole({ initialTrace, initialConversation }: { initialTrace?: string | null; initialConversation?: string | null }) {
  const [list, setList] = useState<TraceListView | null>(null)
  // 从风险详情跳来时带会话 ID：列表先按该会话筛选
  const [filters, setFilters] = useState<{ status?: string; conversationId?: string; hasRepair: boolean }>(
    { hasRepair: false, ...(initialConversation ? { conversationId: initialConversation } : {}) })
  const [currentId, setCurrentId] = useState<string | null>(initialTrace ?? null)
  const [detail, setDetail] = useState<TraceDetailView | null>(null)
  const [view, setView] = useState<'编排' | '引用'>('编排')
  const [inspect, setInspect] = useState<string | null>(null)
  const [lit, setLit] = useState<Set<string> | null>(null)
  const timer = useRef<number | null>(null)

  const load = useCallback(async () => {
    const data = await platformApi.traces(filters).catch(() => ({ items: [], total: 0 }))
    setList(data)
    setCurrentId((old) => old ?? data.items[0]?.traceId ?? null)
  }, [filters])
  useEffect(() => { void load() }, [load])
  useEffect(() => { if (initialTrace) setCurrentId(initialTrace) }, [initialTrace])
  useEffect(() => { if (initialConversation) { setFilters((f) => ({ ...f, conversationId: initialConversation })); setCurrentId(null) } }, [initialConversation])
  useEffect(() => {
    if (!currentId) { setDetail(null); return }
    let live = true
    platformApi.trace(currentId).then((d) => { if (live) setDetail(d) }).catch(() => { if (live) setDetail(null) })
    return () => { live = false }
  }, [currentId])

  const lanes = useMemo(() => (detail ? buildLanes(detail.startedAt, detail.spans) : { rows: [], total: 1 }), [detail])
  const stop = () => { if (timer.current) window.clearTimeout(timer.current); timer.current = null; setLit(null) }
  useEffect(() => stop, [currentId])
  const play = () => {
    if (timer.current) { stop(); return }
    const frames = replayFrames(lanes.rows, 4)
    const seen = new Set<string>()
    setLit(new Set())
    const step = (i: number) => {
      if (i >= frames.length) { timer.current = window.setTimeout(() => { timer.current = null; setLit(null) }, 1200); return }
      timer.current = window.setTimeout(() => { seen.add(frames[i].spanId); setLit(new Set(seen)); step(i + 1) }, Math.min(1500, frames[i].delay + 120))
    }
    step(0)
  }
  const exportTrace = async () => {
    if (!detail) return
    const data = await platformApi.traceExport(detail.traceId)
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const a = document.createElement('a'); a.href = url; a.download = `${detail.traceId}.json`; a.click(); URL.revokeObjectURL(url)
  }
  const span = detail?.spans.find((s) => s.spanId === inspect) ?? null

  return <div className="yt-trace" aria-label="Agent 追踪">
    <div className="yt-trace-filters">
      <Input allowClear size="small" placeholder="会话号" defaultValue={initialConversation ?? undefined} style={{ width: 160 }} onPressEnter={(e) => setFilters((f) => ({ ...f, conversationId: (e.target as HTMLInputElement).value.trim() || undefined }))}
        onChange={(e) => { if (!e.target.value) setFilters((f) => ({ ...f, conversationId: undefined })) }} />
      <Select allowClear size="small" placeholder="结果" style={{ width: 110 }} value={filters.status} onChange={(status) => setFilters((f) => ({ ...f, status }))}
        options={['sent', 'handoff', 'failed'].map((v) => ({ value: v, label: STATUS[v] }))} />
      <Checkbox checked={filters.hasRepair} onChange={(e) => setFilters((f) => ({ ...f, hasRepair: e.target.checked }))}>含修复</Checkbox>
      <span className="r">{list ? `${list.total} 条` : ''}</span>
    </div>
    <div className="yt-trace-body">
      <ol className="yt-trace-list" aria-label="追踪列表">
        {(list?.items ?? []).map((t) => {
          const sum = Math.max(1, t.lanes.reduce((a, l) => a + Number(l.durationMs ?? 0), 0))
          return <li key={t.traceId}><button type="button" className={t.traceId === currentId ? 'on' : undefined} onClick={() => setCurrentId(t.traceId)}>
            <span className="t yt-num">{hm(t.startedAt)}</span><b>{t.buyerAlias ?? t.conversationId ?? t.graph}</b>
            <span className={`st is-${t.status}`}>{STATUS[t.status] ?? t.status}</span><span className="d yt-num">{secs(t.startedAt, t.endedAt)}</span>
            <span className="mini">{t.lanes.map((l, i) => <i key={i} style={{ flexGrow: Number(l.durationMs ?? 0) / sum }} />)}</span>
          </button></li>
        })}
        {list && !list.items.length && <li className="yt-empty">暂无追踪</li>}
      </ol>
      <section className="yt-trace-detail">
        {detail ? <>
          <div className="yt-trace-head">
            <Segmented size="small" value={view} onChange={(v) => setView(v as typeof view)} options={['编排', '引用']} />
            <span className="meta">{detail.traceId} · {detail.orchestration === 'multi' ? '多 Agent' : '单流程'} · {STATUS[detail.status] ?? detail.status}</span>
            <Button size="small" icon={lit ? <PauseOutlined /> : <CaretRightOutlined />} onClick={play}>回放</Button>
            <Button size="small" icon={<DownloadOutlined />} onClick={() => void exportTrace()}>导出</Button>
          </div>
          {view === '编排' && <OrchestrationTree startedAt={detail.startedAt} spans={detail.spans} lit={lit} selected={inspect} onSelect={setInspect}
            trigger={detail.triggerText ?? null} outcome={detail.outcomeText ?? null} outcomeStatus={detail.status} />}
          {view === '引用' && <CitationChain citations={detail.citations} />}
        </> : <p className="yt-empty">选择一条追踪</p>}
      </section>
    </div>
    <SpanInspector span={span} models={detail ? modelsOf(detail.spans, inspect) : []} onClose={() => setInspect(null)} />
  </div>
}
