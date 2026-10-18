import { Drawer, Tabs } from 'antd'
import { useEffect, useState } from 'react'
import { platformApi } from '../../api/client'
import { spanLabel, type TraceSpan } from './traceModel'

const Section = ({ title, sha }: { title: string; sha?: string | null }) => sha ? <><h4>{title}</h4><Artifact sha={sha} /></> : null

function Artifact({ sha }: { sha?: string | null }) {
  const [content, setContent] = useState<string>('')
  useEffect(() => {
    let live = true
    if (!sha) { setContent(''); return }
    platformApi.traceArtifact(sha).then((a) => { if (live) setContent(typeof a.content === 'string' ? a.content : JSON.stringify(a.content, null, 2)) })
      .catch(() => { if (live) setContent('读取失败') })
    return () => { live = false }
  }, [sha])
  return sha ? <pre className="yt-artifact">{content || '…'}</pre> : <p className="yt-empty">无</p>
}

/** 节点检查器：输入 / 输出 / 版本 / 用量 / 问题。Agent 自身的输入输出摘要在前，其下最后一次模型调用的原始输入输出在后。 */
export function SpanInspector({ span, models = [], onClose }: { span: TraceSpan | null; models?: TraceSpan[]; onClose: () => void }) {
  // Agent 节点的模型信息来自其下的模型调用跨度
  const info = models.at(-1) ?? span
  const sum = (key: 'promptTokens' | 'completionTokens' | 'cachedTokens') => models.length ? models.reduce((a, m) => a + (m[key] ?? 0), 0) : span?.[key]
  const kv = (rows: [string, unknown][]) => <dl className="yt-kv">{rows.filter(([, v]) => v != null && v !== '').map(([k, v]) =>
    <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl>
  const lastModel = models.at(-1)
  const io = (own: string | null | undefined, model: string | null | undefined, ownTitle: string, modelTitle: string) =>
    own || model ? <><Section title={ownTitle} sha={own} />{model && model !== own && <Section title={modelTitle} sha={model} />}</> : <p className="yt-empty">本节点没有记录{ownTitle.slice(-2)}</p>
  return <Drawer rootClassName="yt-insp" open={Boolean(span)} onClose={onClose} title={span ? `${spanLabel(span)}${span.attempt > 1 ? ` @${span.attempt}` : ''}` : ''} size="large">
    {span?.summary && <p className="yt-insp-sum">{span.summary}</p>}
    {span && <Tabs items={[
      { key: 'in', label: '输入', children: io(span.inputArtifact, lastModel?.inputArtifact, '节点输入', '模型输入（最后一次调用）') },
      { key: 'out', label: '输出', children: io(span.outputArtifact, lastModel?.outputArtifact, '节点输出', '模型原始输出（最后一次调用）') },
      { key: 'ver', label: '版本', children: kv([['提示词', info?.promptCode ? `${info.promptCode}@${info.promptRevision ?? ''}` : null], ['提示词摘要', info?.promptSha256?.slice(0, 12)],
        ['契约', info?.contractVersion], ['档位', info?.tier], ['请求模型', info?.modelRequested], ['返回模型', info?.modelReturned], ['Mock', info?.isMock == null ? null : info.isMock ? '是' : '否']]) },
      { key: 'use', label: '用量', children: kv([['耗时', span.durationMs != null ? `${span.durationMs} ms` : null], ['模型调用', models.length || null], ['输入 Token', sum('promptTokens')], ['输出 Token', sum('completionTokens')],
        ['缓存 Token', sum('cachedTokens')], ['结束原因', info?.finishReason]]) },
      { key: 'issue', label: '问题', children: <>{kv([['状态', span.status], ['错误', span.errorCode], ['详情', span.errorDetail]])}
        {(span.reasons ?? []).length > 0 && <ul className="yt-reasons">{(span.reasons ?? []).map((r, i) => <li key={i}>{typeof r === 'string' ? r : JSON.stringify(r)}</li>)}</ul>}</> },
    ]} />}
  </Drawer>
}
