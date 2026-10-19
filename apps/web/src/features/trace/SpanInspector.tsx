import { CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { Drawer, Segmented, Tabs, Typography } from 'antd'
import { useEffect, useState, type ReactNode } from 'react'
import { platformApi } from '../../api/client'
import { checksOf, spanLabel, type TraceSpan } from './traceModel'

const ROLE: Record<string, string> = { system: '系统提示', user: '输入资料', assistant: '模型回答', tool: '工具' }
const REPLY_STYLE: Record<string, string> = { recommended: '推荐', concise: '简洁', reassuring: '安抚' }

const parse = (raw: unknown): unknown => {
  if (typeof raw !== 'string') return raw
  const text = raw.trim()
  if (!(text.startsWith('{') || text.startsWith('['))) return raw
  try { return JSON.parse(text) } catch { return raw }
}
const isChat = (v: unknown): v is { role: string; content: unknown }[] =>
  Array.isArray(v) && v.length > 0 && v.every((m) => m && typeof m === 'object' && 'role' in m && 'content' in m)
const isEmpty = (v: unknown) => v == null || v === '' || (Array.isArray(v) && !v.length) || (typeof v === 'object' && !Array.isArray(v) && !Object.keys(v as object).length)

/** 把节点产物读成人能看懂的样子：对话按角色分段、回复画成气泡、字段成对排列；原始 JSON 另切。 */
export function Readable({ value, depth = 0 }: { value: unknown; depth?: number }): ReactNode {
  const v = parse(value)
  if (isEmpty(v)) return <span className="yt-rd-none">无</span>
  if (typeof v === 'string') return v.length > 280
    ? <Typography.Paragraph className="yt-rd-text" ellipsis={{ rows: 4, expandable: 'collapsible', symbol: (open) => (open ? '收起' : '展开') }}>{v}</Typography.Paragraph>
    : <span className="yt-rd-text">{v}</span>
  if (typeof v !== 'object') return <span className="yt-rd-text yt-num">{typeof v === 'boolean' ? (v ? '是' : '否') : String(v)}</span>
  if (isChat(v)) return <div className="yt-rd-chat">{v.map((m, i) => <div key={i} className={`yt-rd-msg is-${m.role}`}>
    <span className="r">{ROLE[m.role] ?? m.role}</span>
    {typeof m.content === 'string' && m.role === 'system'
      ? <Typography.Paragraph className="yt-rd-text" ellipsis={{ rows: 3, expandable: 'collapsible', symbol: (open) => (open ? '收起' : '展开') }}>{m.content}</Typography.Paragraph>
      : <Readable value={m.content} depth={depth + 1} />}
  </div>)}</div>
  if (Array.isArray(v)) {
    if (v.every((x) => typeof x === 'string' || typeof x === 'number')) {
      return v.some((x) => String(x).length > 24)
        ? <ul className="yt-rd-list">{v.map((x, i) => <li key={i}>{String(x)}</li>)}</ul>
        : <span className="yt-rd-chips">{v.map((x, i) => <i key={i}>{String(x)}</i>)}</span>
    }
    return <div className="yt-rd-items">{v.map((x, i) => {
      if (x && typeof x === 'object' && 'body' in x) {
        const r = x as { body: string; style?: string }
        return <div key={i} className="yt-rd-bubble">{r.style && <span className="r">{REPLY_STYLE[r.style] ?? r.style}</span>}{r.body}</div>
      }
      return <div key={i} className="yt-rd-item"><Readable value={x} depth={depth + 1} /></div>
    })}</div>
  }
  const entries = Object.entries(v as Record<string, unknown>).filter(([, x]) => !isEmpty(x))
  if (!entries.length) return <span className="yt-rd-none">无</span>
  return <dl className={`yt-rd-kv${depth ? ' is-nested' : ''}`}>{entries.map(([k, x]) =>
    <div key={k}><dt>{k}</dt><dd><Readable value={x} depth={depth + 1} /></dd></div>)}</dl>
}

function Artifact({ sha, title }: { sha: string; title: string }) {
  const [content, setContent] = useState<unknown>(undefined)
  const [raw, setRaw] = useState(false)
  useEffect(() => {
    let live = true
    setContent(undefined)
    platformApi.traceArtifact(sha).then((a) => { if (live) setContent(a.content) }).catch(() => { if (live) setContent('读取失败') })
    return () => { live = false }
  }, [sha])
  const text = typeof content === 'string' ? content : JSON.stringify(content, null, 2)
  return <section className="yt-rd">
    <h4>{title}<Segmented size="small" value={raw ? '原始' : '可读'} options={['可读', '原始']} onChange={(x) => setRaw(x === '原始')} /></h4>
    {content === undefined ? <span className="yt-rd-none">…</span> : raw ? <pre className="yt-artifact">{text}</pre> : <Readable value={content} />}
  </section>
}

const Checks = ({ span }: { span: TraceSpan }) => {
  const checks = checksOf(span)
  return checks.length ? <ul className="yt-insp-checks">{checks.map((c) => <li key={c.name} className={c.hit ? 'is-hit' : undefined}>
    {c.hit ? <CloseOutlined /> : <CheckOutlined />}<b>{c.name}</b><span>{c.detail}</span></li>)}</ul> : null
}

const REASON_KEYS: Record<string, string> = { verifyReasons: '需事实核验的原因', reviewFlags: '待复核', auxiliaryDropped: '撤下的辅助内容' }

/** 节点检查器（反馈 10-19 #4）：只出现有内容的页签；产物默认按可读方式展示。 */
export function SpanInspector({ span, models = [], onClose }: { span: TraceSpan | null; models?: TraceSpan[]; onClose: () => void }) {
  const info = models.at(-1) ?? span
  const sum = (key: 'promptTokens' | 'completionTokens' | 'cachedTokens') => models.length ? models.reduce((a, m) => a + (m[key] ?? 0), 0) : span?.[key]
  const kv = (rows: [string, unknown][]) => {
    const shown = rows.filter(([, v]) => v != null && v !== '')
    return shown.length ? <dl className="yt-kv">{shown.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl> : null
  }
  const lastModel = models.at(-1)
  const io = (own: string | null | undefined, model: string | null | undefined, ownTitle: string, modelTitle: string) =>
    own || model ? <>{own && <Artifact sha={own} title={ownTitle} />}{model && model !== own && <Artifact sha={model} title={modelTitle} />}</> : null
  const reasons = (span?.reasons ?? []).filter((r) => !(r && typeof r === 'object' && 'checks' in (r as object)))
  const textReasons = reasons.filter((r) => typeof r === 'string') as string[]
  const objReasons = reasons.filter((r) => r && typeof r === 'object') as Record<string, unknown>[]
  const tabs = span ? [
    { key: 'in', label: '输入', children: io(span.inputArtifact, lastModel?.inputArtifact, '节点读到的', '发给模型的（最后一次调用）') },
    { key: 'out', label: '输出', children: io(span.outputArtifact, lastModel?.outputArtifact, '节点交出的', '模型原文（最后一次调用）') },
    { key: 'model', label: '模型', children: models.length || info?.modelRequested ? kv([
      ['请求模型', info?.modelRequested], ['返回模型', info?.modelReturned], ['调用次数', models.length || null],
      ['输入 Token', sum('promptTokens')], ['缓存命中', sum('cachedTokens')], ['输出 Token', sum('completionTokens')],
      ['结束原因', info?.finishReason], ['提示词', info?.promptCode ? `${info.promptCode}@${info.promptRevision ?? ''}` : null],
      ['契约', info?.contractVersion], ['档位', info?.tier], ['Mock', info?.isMock == null ? null : info.isMock ? '是' : '否']]) : null },
    { key: 'issue', label: '问题', children: textReasons.length || objReasons.length || span.errorCode ? <>
      {kv([['错误', span.errorCode], ['详情', span.errorDetail]])}
      {textReasons.length > 0 && <ul className="yt-reasons">{textReasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
      {objReasons.map((r, i) => <Readable key={i} value={Object.fromEntries(Object.entries(r).map(([k, x]) => [REASON_KEYS[k] ?? k, x]))} />)}
    </> : null },
  ].filter((t) => t.children) : []
  return <Drawer rootClassName="yt-insp" open={Boolean(span)} onClose={onClose} title={span ? `${spanLabel(span)}${span.attempt > 1 ? ` · 第 ${span.attempt} 次` : ''}` : ''} size="large">
    {span && <>
      <div className="yt-insp-head">
        {span.summary && <p className="yt-insp-sum">{span.summary}</p>}
        <span className="meta yt-num">{span.durationMs != null ? `${span.durationMs} ms` : ''}</span>
      </div>
      <Checks span={span} />
      {tabs.length > 0 && <Tabs items={tabs} />}
    </>}
  </Drawer>
}
