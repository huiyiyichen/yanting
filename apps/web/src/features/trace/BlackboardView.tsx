import { Button } from 'antd'
import { useState } from 'react'
import { platformApi } from '../../api/client'
import { spanLabel, type TraceSpan } from './traceModel'

const text = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v, null, 2))

/** 视图 4：黑板。按时间列出各节点写入；选两版同一槽位看差异。 */
export function BlackboardView({ spans }: { spans: TraceSpan[] }) {
  const writes = spans.filter((s) => s.outputArtifact && s.kind !== 'model').sort((a, b) => a.seq - b.seq)
  const [pick, setPick] = useState<string[]>([])
  const [diff, setDiff] = useState<{ a: string[]; b: string[] } | null>(null)
  if (!writes.length) return <p className="yt-empty">本次没有槽位写入</p>
  const toggle = (id: string) => setPick((old) => old.includes(id) ? old.filter((x) => x !== id) : [...old.slice(-1), id])
  const compare = async () => {
    const [a, b] = pick.map((id) => writes.find((w) => w.spanId === id)!)
    const [x, y] = await Promise.all([platformApi.traceArtifact(a.outputArtifact!), platformApi.traceArtifact(b.outputArtifact!)])
    setDiff({ a: text(x.content).split('\n'), b: text(y.content).split('\n') })
  }
  return <div className="yt-board">
    <table><thead><tr><th /><th>槽位</th><th>写入者</th><th>版本</th></tr></thead><tbody>
      {writes.map((w) => <tr key={w.spanId}><td><input type="checkbox" aria-label={`选择 ${spanLabel(w)} @${w.attempt}`} checked={pick.includes(w.spanId)} onChange={() => toggle(w.spanId)} /></td>
        <td>{w.name}</td><td>{spanLabel(w)}</td><td>@{w.attempt}</td></tr>)}
    </tbody></table>
    <Button size="small" disabled={pick.length !== 2} onClick={() => void compare()}>对比两版</Button>
    {diff && <div className="yt-diff">{Array.from({ length: Math.max(diff.a.length, diff.b.length) }, (_, i) => {
      const same = diff.a[i] === diff.b[i]
      return same ? <pre key={i}>{diff.a[i]}</pre> : <div key={i}>{diff.a[i] != null && <pre className="is-del">- {diff.a[i]}</pre>}{diff.b[i] != null && <pre className="is-add">+ {diff.b[i]}</pre>}</div>
    })}</div>}
  </div>
}
