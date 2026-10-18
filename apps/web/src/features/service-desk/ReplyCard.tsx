import { BulbOutlined, CheckCircleFilled, CheckOutlined, CloseOutlined, DownOutlined, EditOutlined, MinusCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { Button, Dropdown, Input, Tooltip, message } from 'antd'
import { useRef, useState, type CSSProperties, type ReactNode } from 'react'
import type { ConsumerServiceAssistantView } from '../../api/client'
import { flyToComposer } from './flyToComposer'

type Suggestion = ConsumerServiceAssistantView['replySuggestions'][number]
type Instruction = 'gentler' | 'concise' | 'professional'

const STYLES: Record<string, string> = { recommended: '推荐', concise: '简洁', reassuring: '安抚' }
const REWRITES: { key: Instruction; label: string }[] = [
  { key: 'gentler', label: '更温和' }, { key: 'concise', label: '更简洁' }, { key: 'professional', label: '更专业' },
]

type Source = NonNullable<ConsumerServiceAssistantView['groundingSources']>[number]

/** 依据引用转成客服可读标签（工单号、订单尾号、本次会话、商品资料名）；内部编号只放悬停。 */
export function sourceLabel(ref: string, sources: Source[] = []): string {
  const [kind, id = ''] = ref.split(':')
  if (kind === 'work_order' || kind === 'ticket') return `工单 ${id}`
  if (kind === 'order') return `订单 …${id.slice(-4)}`
  if (kind === 'message' || kind === 'conversation' || kind === 'customer_message' || kind === 'staff_message') return '本次会话'
  if (kind === 'knowledge') {
    const title = sources.find((source) => source.sourceId === ref)?.label
    return title ? `商品资料 · ${title}` : '商品资料'
  }
  return '其他依据'
}

/** 把有依据的短片段（非整段）标成金色引用。 */
function marked(body: string, claims: Suggestion['claims'], sources: Source[]): ReactNode[] {
  const spans = (claims ?? []).filter((claim) => claim.text && claim.text !== body && body.includes(claim.text))
    .map((claim) => ({ start: body.indexOf(claim.text), text: claim.text, title: [...new Set(claim.sourceRefs.map((ref) => sourceLabel(ref, sources)))].join('、') }))
    .sort((a, b) => a.start - b.start)
  const out: ReactNode[] = []
  let at = 0
  for (const span of spans) {
    if (span.start < at) continue
    if (span.start > at) out.push(body.slice(at, span.start))
    out.push(<span key={span.start} className="yt-reply-ref" title={span.title}
      style={{ '--i': out.filter((node) => typeof node !== 'string').length } as CSSProperties}>{span.text}</span>)
    at = span.start + span.text.length
  }
  if (at < body.length) out.push(body.slice(at))
  return out
}

/** 回复建议卡：风格切换、编辑、改写、单风格重生成；核验通过前不可采用，采用只填草稿不发送。 */
export function ReplyCard({ suggestions, sources = [], adoptable, automatic, generating, onAdopt, onIgnore, onRegenerate, onRewrite }: {
  suggestions: Suggestion[]
  sources?: Source[]
  adoptable: boolean
  automatic: boolean
  generating: boolean
  onAdopt: (style: string, body: string, edited: boolean) => void
  onIgnore: (style: string) => void
  onRegenerate: (style: string) => void
  onRewrite: (style: string, body: string, instruction: Instruction) => Promise<string>
}) {
  const [style, setStyle] = useState(suggestions[0]?.style ?? 'recommended')
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState(false)
  const [rewriting, setRewriting] = useState(false)
  const [toast, holder] = message.useMessage()
  const bodyRef = useRef<HTMLParagraphElement>(null)
  const current = suggestions.find((item) => item.style === style) ?? suggestions[0]
  if (!current) return null
  const original = current.body
  const basis = [...new Map((current.claims ?? []).flatMap((claim) => claim.sourceRefs)
    .map((ref) => [sourceLabel(ref, sources), ref] as const)).entries()].slice(0, 5)
  const body = edits[current.style] ?? original
  const edited = body !== original
  const blocked = !adoptable || automatic || generating
  // 草稿模式核验未通过：仍可采用，盖“待确认”章并在悬停时给出原因
  const notes = current.reviewNotes ?? []
  // X-4：核验通过（可采用且不在生成中）才盖“已核验”章、画金色下划线
  const verified = adoptable && !generating && notes.length === 0
  const reason = automatic ? 'AI 接待中' : generating ? '生成中' : !adoptable ? '待核验' : undefined

  const rewrite = async (instruction: Instruction) => {
    setRewriting(true)
    try {
      const text = await onRewrite(current.style, body, instruction)
      setEdits((old) => ({ ...old, [current.style]: text }))
    } catch (err) { void toast.warning((err as Error).message) }
    finally { setRewriting(false) }
  }

  return <article className={`yt-reply${generating ? ' is-refreshing' : ''}${verified ? ' is-verified' : ''}`} aria-label="回复建议">
    {holder}
    <div className="yt-reply-head">
      <h3><BulbOutlined />回复建议</h3>
      {verified && <span className="yt-reply-stamp">已核验</span>}
      {notes.length > 0 && !generating && <Tooltip title={<ul className="yt-reply-notes">{notes.map((note) => <li key={note}>{note}</li>)}</ul>}>
        <span className="yt-reply-stamp is-review" aria-label={`待确认：${notes.join('；')}`}>待确认</span></Tooltip>}
      {suggestions.length > 1 && <div className="yt-reply-styles" role="tablist" aria-label="回复风格">
        {suggestions.map((item) => <button type="button" role="tab" key={item.style}
          aria-selected={item.style === current.style} className={item.style === current.style ? 'on' : undefined}
          onClick={() => { setStyle(item.style); setEditing(false) }}>{STYLES[item.style] ?? item.style}</button>)}
      </div>}
      <Tooltip title="重新生成此风格"><Button size="small" type="text" icon={<ReloadOutlined />}
        aria-label="重新生成此风格" disabled={generating} onClick={() => onRegenerate(current.style)} /></Tooltip>
    </div>
    {editing
      ? <Input.TextArea aria-label="编辑回复建议" autoSize={{ minRows: 3, maxRows: 8 }} maxLength={800} value={body}
        onChange={(event) => setEdits((old) => ({ ...old, [current.style]: event.target.value }))} />
      : <p className="yt-reply-body" ref={bodyRef}>{edited ? body : marked(body, current.claims, sources)}</p>}
    {(current.empathyDimensions?.length ?? 0) > 0 && <div className="yt-reply-empathy">
      {current.empathyDimensions!.map((item) =>
        <span key={item.key} title={item.reason} className={item.status === 'present' ? 'is-present' : 'is-missing'}>
          {item.status === 'present' ? <CheckCircleFilled /> : <MinusCircleOutlined />} {item.label}</span>)}
    </div>}
    {basis.length > 0 && <ul className="yt-reply-basis" aria-label="回复依据">
      {basis.map(([label, ref]) => <li key={label} title={ref}>{label}</li>)}</ul>}
    <div className="yt-reply-actions">
      <Tooltip title={reason}><span>
        <Button type="primary" size="small" icon={<CheckOutlined />} disabled={blocked}
          onClick={() => { void flyToComposer(bodyRef.current, body); onAdopt(current.style, body, edited) }}>采用</Button>
      </span></Tooltip>
      <Button size="small" icon={<EditOutlined />} onClick={() => setEditing((value) => !value)}>{editing ? '完成' : '编辑'}</Button>
      <Dropdown disabled={generating || rewriting} trigger={['click']}
        menu={{ items: REWRITES.map((item) => ({ key: item.key, label: item.label })), onClick: ({ key }) => void rewrite(key as Instruction) }}>
        <Button size="small" loading={rewriting}>改写 <DownOutlined /></Button>
      </Dropdown>
      <Tooltip title="忽略"><Button size="small" type="text" icon={<CloseOutlined />} aria-label="忽略"
        onClick={() => onIgnore(current.style)} /></Tooltip>
    </div>
  </article>
}
