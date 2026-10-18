import type { LaneRow } from './traceModel'
import { AGENT_LABEL } from './traceModel'

/** 视图 2：流程图。静态编排图，本次走过的节点高亮，未走的虚线。 */
const STAGES: string[][] = [['safety_gate'], ['triage'], ['trajectory', 'knowledge', 'vision'], ['composer'], ['program_check', 'verifier'], ['output_gate', 'send_gate']]

export function TraceFlow({ rows, onSelect }: { rows: LaneRow[]; onSelect: (spanId: string) => void }) {
  const seen = new Map<string, LaneRow[]>()
  for (const r of rows) seen.set(r.span.name, [...(seen.get(r.span.name) ?? []), r])
  const extra = rows.filter((r) => !STAGES.flat().includes(r.span.name) && r.kind !== 'model')
  return <div className="yt-flow" aria-label="流程图">
    {[...STAGES, ...(extra.length ? [[...new Set(extra.map((r) => r.span.name))]] : [])].map((stage, i) => <div key={i} className="yt-flow-col">
      {stage.map((name) => {
        const hit = seen.get(name) ?? []
        const last = hit.at(-1)
        const state = !last ? 'none' : last.status === 'skipped' ? 'skipped' : last.status === 'ok' ? 'ok' : 'fail'
        return <button type="button" key={name} className={`yt-flow-node is-${state}`} disabled={!last} onClick={() => last && onSelect(last.spanId)}>
          <b>{AGENT_LABEL[name] ?? last?.label ?? name}</b>
          {hit.length > 1 && <em>×{hit.length}</em>}
          {state === 'skipped' && last?.note && <small>{last.note}</small>}
          {state === 'none' && <small>未运行</small>}
        </button>
      })}
    </div>)}
  </div>
}
