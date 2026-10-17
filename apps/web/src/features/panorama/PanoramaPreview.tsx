import { Button } from 'antd'
import { Link } from 'react-router-dom'
import { UserOutlined } from '@ant-design/icons'
import type { MessageView, PanoramaItem } from '../../api/client'
import { EmotionSwatch, SWATCH_LABEL, type SwatchLevel } from '../voiceprint/EmotionSwatch'
import { shHourMinute } from '../service-desk/shTime'
import { LANE_LABEL, clock, waitSeconds } from './panoramaModel'

type Run = NonNullable<PanoramaItem['currentRun']>

const DONE = new Set(['done', 'skipped'])

/** AI 处理：按追踪里实际运行的 Agent 列出，并行组缩进，逐项耗时（多 Agent 8.2）。 */
function Steps({ run, title }: { run: Run; title: string }) {
  const total = run.outcome === 'sent' ? `${(run.steps.reduce((sum, step) => sum + step.durationMs, 0) / 1000).toFixed(1)} 秒` : ''
  return <section className="yt-pcard" aria-label={title}>
    <h3>{title}<span className="r">{total}</span></h3>
    <ol className="yt-psteps">{run.steps.map((step, i) => {
      const par = Boolean(step.group)
      const first = par && run.steps[i - 1]?.group !== step.group
      return <li key={`${step.name}-${i}`} className={`is-${step.status}${par ? ' is-par' : ''}${first ? ' is-par-first' : ''}`}>
        <span>{step.name}{(step.attempts ?? 1) > 1 && <em className="x">×{step.attempts}</em>}</span>
        <span className="d">{step.status === 'fail' ? '转人工' : step.status === 'skipped' ? '跳过'
          : DONE.has(step.status) || step.durationMs ? `${(step.durationMs / 1000).toFixed(1)}s` : ''}</span>
      </li>
    })}</ol>
    {run.traceId && <Link className="yt-ptrace" to={`/platform/models?tab=trace&trace=${encodeURIComponent(run.traceId)}`}>查看追踪</Link>}
  </section>
}

/** 预览栏：头部卡、转人工原因、AI 处理步骤、最近 6 条消息。 */
export function PanoramaPreview({ item, messages, now, busy, onTakeover, onOpen }: {
  item: PanoramaItem | null
  messages: MessageView[]
  now: number
  busy: boolean
  onTakeover: (id: string) => void
  onOpen: (id: string) => void
}) {
  if (!item) return <aside className="yt-ppreview" aria-label="会话预览"><section className="yt-pcard"><h3>未选择会话</h3></section></aside>
  const wait = waitSeconds(item, now)
  const current = item.emotionBands.at(-1) as SwatchLevel | undefined
  const customers = messages.filter((message) => message.senderRole === 'customer').map((message) => message.messageId)
  /** 消费者消息与 emotionBands（最近 6 条）从末尾对齐。 */
  const levelOf = (id: string): SwatchLevel | undefined =>
    item.emotionBands[item.emotionBands.length - (customers.length - customers.indexOf(id))] as SwatchLevel | undefined
  return <aside className="yt-ppreview" aria-label="会话预览">
    <section className="yt-pcard">
      <div className="yt-phead">
        <EmotionSwatch bands={item.emotionBands} highRisk={item.highRisk} size="lg" />
        <div>
          <b>{item.buyerAlias}<span className={`yt-lane-chip is-${item.lane}`}>{item.lane === 'human' ? `人工 · ${item.handler ?? '客服'}` : LANE_LABEL[item.lane]}</span></b>
          {item.scene && <div className="sub">{item.scene}{item.productName ? ` · ${item.productName}` : ''}</div>}
          <div className="now">{current && <span><i className={`is-${current}`} />{SWATCH_LABEL[current]}</span>}
            {wait != null && <span>等待 <span className="t">{clock(wait)}</span></span>}</div>
        </div>
      </div>
      <div className="yt-pacts">
        {item.lane !== 'human' && <Button type="primary" icon={<UserOutlined />} loading={busy} onClick={() => onTakeover(item.conversationId)}>接管</Button>}
        <Button onClick={() => onOpen(item.conversationId)}>打开会话</Button>
      </div>
    </section>
    {item.lane === 'wait' && item.handoffReason && <section className="yt-pcard" aria-label="转人工原因">
      <div className="yt-preason"><b>{item.handoffReason}</b>{item.handoffQuote && <q>{item.handoffQuote}</q>}</div>
    </section>}
    {item.currentRun ? <Steps run={item.currentRun} title="AI 处理中" />
      : item.aiJob === 'queued' ? <section className="yt-pcard"><h3>AI 排队中</h3></section>
        : item.lastRun ? <Steps run={item.lastRun} title="上一轮 AI 处理" /> : null}
    <section className="yt-pcard" aria-label="最近消息">
      <h3>最近消息</h3>
      <div className="yt-pmsgs">{messages.slice(-6).map((message) => {
        if (message.senderRole === 'system') return <div key={message.messageId} className="yt-pm is-sys"><span>{message.body}</span></div>
        if (message.senderRole === 'customer') {
          const level = levelOf(message.messageId)
          return <div key={message.messageId} className={`yt-pm is-c${level ? ` is-${level}` : ''}`}>
            <div className="who">{item.buyerAlias} <span className="t">{shHourMinute(message.createdAt)}</span>
              {level && <span className="e"><i className={`is-${level}`} />{SWATCH_LABEL[level]}</span>}</div>
            <div className="bb">{message.body}</div></div>
        }
        const ai = message.senderRole === 'assistant'
        return <div key={message.messageId} className={`yt-pm is-s ${ai ? 'is-a' : 'is-o'}`}>
          <div className="who"><span className="t">{shHourMinute(message.createdAt)}</span>{ai ? '智能助手' : '客服'}</div>
          <div className="bb">{message.body}</div></div>
      })}</div>
    </section>
  </aside>
}
