import { BookOutlined, CarOutlined, FileTextOutlined, PictureOutlined, RightOutlined, StarOutlined } from '@ant-design/icons'
import { useEffect, useState, type ReactNode } from 'react'

/** 诉求：主诉求深色，其余为客户提到的待办事项，待确认信息用琥珀色。 */
export function IntentRow({ primary, items, missing }: { primary?: string; items: string[]; missing: string[] }) {
  const rest = [...new Set(items.filter((item) => item && item !== primary))].slice(0, 3)
  if (!primary && !rest.length && !missing.length) return null
  return <div className="yt-intent" role="group" aria-label="诉求">
    <span className="lb">诉求</span>
    {primary && <span className="yt-chip-x ink">{primary}</span>}
    {rest.map((item) => <span key={item} className="yt-chip-x">{item}</span>)}
    {missing.slice(0, 2).map((item) => <span key={item} className="yt-chip-x mid">待确认 {item}</span>)}
  </div>
}

const storeKey = (scope: string) => `yt-next-steps:${scope}`

/** 下一步：可勾选清单，按会话与建议版本记在本机；勾完沉到底部并划掉。 */
export function NextSteps({ scope, steps, title = '下一步' }: { scope: string; steps: string[]; title?: string }) {
  const [done, setDone] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem(storeKey(scope)) ?? '[]') as string[] } catch { return [] }
  })
  useEffect(() => {
    try { setDone(JSON.parse(localStorage.getItem(storeKey(scope)) ?? '[]') as string[]) } catch { setDone([]) }
  }, [scope])
  if (!steps.length) return null
  const toggle = (step: string) => setDone((old) => {
    const next = old.includes(step) ? old.filter((item) => item !== step) : [...old, step]
    try { localStorage.setItem(storeKey(scope), JSON.stringify(next)) } catch { /* 本机存储不可用时只在内存中 */ }
    return next
  })
  const ordered = [...steps.filter((s) => !done.includes(s)), ...steps.filter((s) => done.includes(s))]
  return <section className="service-section yt-card" aria-label={title}>
    <h3>{title}<span className="r">{steps.filter((s) => done.includes(s)).length}/{steps.length}</span></h3>
    <ul className="yt-todo">
      {ordered.map((step) => <li key={step} className={done.includes(step) ? 'is-done' : undefined}>
        <label><input type="checkbox" checked={done.includes(step)} onChange={() => toggle(step)} /><span>{step}</span></label>
      </li>)}
    </ul>
  </section>
}

export type Fold = { key: string; label: string; count: number; icon: 'knowledge' | 'order' | 'ticket' | 'image' | 'advice'; body: ReactNode }
const ICONS = { knowledge: <BookOutlined />, order: <CarOutlined />, ticket: <FileTextOutlined />, image: <PictureOutlined />, advice: <StarOutlined /> }

/** 更多依据：一行一类，带数量；点开就地展开，同一时间只开一项。 */
export function EvidenceFolds({ folds }: { folds: Fold[] }) {
  const [open, setOpen] = useState<string | null>(null)
  const visible = folds.filter((fold) => fold.count > 0 || fold.key === 'knowledge')
  if (!visible.length) return null
  return <section className="service-section yt-card yt-folds" aria-label="更多依据">
    {visible.map((fold) => <div key={fold.key} className={`yt-fold${open === fold.key ? ' is-open' : ''}`}>
      <button type="button" aria-expanded={open === fold.key} onClick={() => setOpen(open === fold.key ? null : fold.key)}>
        {ICONS[fold.icon]}<span>{fold.label}</span><span className="n">{fold.count}</span><RightOutlined className="chev" />
      </button>
      {open === fold.key && <div className="yt-fold-body">{fold.body}</div>}
    </div>)}
  </section>
}

/** 交接摘要：只展示模型生成的 service_summary（1–2 句）；未生成时只标“待生成”，不再拼接聊天原句。 */
export function HandoffSummary({ summary, state }: { summary?: string | null; state: '待生成' | '生成中' | '待更新' | null }) {
  const text = summary?.trim()
  return <section className="service-section yt-card yt-handoff" aria-label="交接摘要">
    <h3>交接摘要{(!text || state) && <span className="r">{state ?? '待生成'}</span>}</h3>
    {text ? <p>{text}</p> : null}
  </section>
}
