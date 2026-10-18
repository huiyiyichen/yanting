import { Drawer, Input } from 'antd'
import { useState } from 'react'
import { platformApi } from '../../api/client'
import { citationChain, type TraceCitation } from './traceModel'

/** 视图 3：引用链。分段 → 来源 → 官方记录；点记录看原始字段。 */
export function CitationChain({ citations }: { citations: TraceCitation[] }) {
  const [q, setQ] = useState('')
  const [record, setRecord] = useState<{ title: string; values: Record<string, unknown> } | null>(null)
  const chain = citationChain(citations).filter((c) => !q || c.sources.some((s) => s.id.includes(q)))
  if (!citations.length) return <p className="yt-empty">本次没有引用</p>
  const open = async (id: string, title: string) => {
    try { setRecord({ title, values: (await platformApi.sourceRecord(id)).values }) } catch { setRecord({ title, values: { 错误: '读取失败' } }) }
  }
  return <div className="yt-chain">
    <Input allowClear size="small" placeholder="按来源搜索，如订单号" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 260 }} />
    {chain.map((c) => <div key={`${c.style}${c.index}`} className="yt-chain-row">
      <p className="seg"><i>{c.index}</i>{c.text}</p>
      <ul>{c.sources.map((s) => <li key={s.id} className={s.ok ? 'is-ok' : 'is-bad'}>
        <span className="src">{s.id}</span><span className="v">{s.ok ? '已核验' : s.verdict}</span>
        {s.record ? <button type="button" disabled={!s.recordId} onClick={() => s.recordId && void open(s.recordId, s.record!)}>{s.record}</button> : <span className="none">无官方记录</span>}
      </li>)}</ul>
    </div>)}
    <Drawer open={Boolean(record)} title={record?.title} onClose={() => setRecord(null)} size="default">
      {record && <dl className="yt-kv">{Object.entries(record.values).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{String(v ?? '')}</dd></div>)}</dl>}
    </Drawer>
  </div>
}
