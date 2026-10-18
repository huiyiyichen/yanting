import { Drawer, Tabs } from 'antd'
import { useEffect, useState } from 'react'
import { platformApi } from '../../api/client'
import { spanLabel, type TraceSpan } from './traceModel'

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

/** 节点检查器：输入 / 输出 / 版本 / 用量 / 问题。 */
export function SpanInspector({ span, models = [], onClose }: { span: TraceSpan | null; models?: TraceSpan[]; onClose: () => void }) {
  // Agent 节点的模型信息来自其下的模型调用跨度
  const info = models.at(-1) ?? span
  const sum = (key: 'promptTokens' | 'completionTokens' | 'cachedTokens') => models.length ? models.reduce((a, m) => a + (m[key] ?? 0), 0) : span?.[key]
  const kv = (rows: [string, unknown][]) => <dl className="yt-kv">{rows.filter(([, v]) => v != null && v !== '').map(([k, v]) =>
    <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>)}</dl>
  return <Drawer open={Boolean(span)} onClose={onClose} title={span ? `${spanLabel(span)}${span.attempt > 1 ? ` @${span.attempt}` : ''}` : ''} size="large">
    {span && <Tabs items={[
      { key: 'in', label: '输入', children: <Artifact sha={span.inputArtifact ?? info?.inputArtifact} /> },
      { key: 'out', label: '输出', children: <Artifact sha={span.outputArtifact ?? info?.outputArtifact} /> },
      { key: 'ver', label: '版本', children: kv([['提示词', info?.promptCode ? `${info.promptCode}@${info.promptRevision ?? ''}` : null], ['提示词摘要', info?.promptSha256?.slice(0, 12)],
        ['契约', info?.contractVersion], ['档位', info?.tier], ['请求模型', info?.modelRequested], ['返回模型', info?.modelReturned], ['Mock', info?.isMock == null ? null : info.isMock ? '是' : '否']]) },
      { key: 'use', label: '用量', children: kv([['耗时', span.durationMs != null ? `${span.durationMs} ms` : null], ['模型调用', models.length || null], ['输入 Token', sum('promptTokens')], ['输出 Token', sum('completionTokens')],
        ['缓存 Token', sum('cachedTokens')], ['结束原因', info?.finishReason]]) },
      { key: 'issue', label: '问题', children: <>{kv([['状态', span.status], ['错误', span.errorCode], ['详情', span.errorDetail]])}
        {(span.reasons ?? []).length > 0 && <ul className="yt-reasons">{span.reasons.map((r, i) => <li key={i}>{typeof r === 'string' ? r : JSON.stringify(r)}</li>)}</ul>}</> },
    ]} />}
  </Drawer>
}
