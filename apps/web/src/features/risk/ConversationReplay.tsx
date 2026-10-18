import { Alert, Button, Skeleton } from 'antd'
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { deskApi, type ServiceScoreView } from '../../api/client'
import { serviceRiskTypeLabels } from '../../contracts/enums'
import { HighlightedText } from '../service-desk/HighlightedText'
import { shHourMinute, shMonthDay } from '../service-desk/shTime'
import { EmotionSwatch, SWATCH_LABEL } from '../voiceprint/EmotionSwatch'
import { EmotionReplay } from './EmotionReplay'

export type FocusHint = { riskType?: string; at?: string | null }
export type ReplayHandle = { focus: (conversationId: string, messageId: string, hint?: FocusHint) => void }

/** 结论行没有原话时，按信号类型→时间最近→最后一条客户消息，找回放里对应的消息。 */
export function resolveFocusMessage(notes: ServiceScoreView['notes'], messageId: string, hint?: FocusHint) {
  if (messageId && notes.some((note) => note.messageId === messageId)) return messageId
  if (!hint) return messageId
  const typed = hint.riskType ? notes.find((note) => (note.signals ?? []).includes(hint.riskType as never)) : undefined
  if (typed) return typed.messageId
  const at = hint.at ? Date.parse(hint.at) : NaN
  const pool = notes.filter((note) => note.role !== 'system')
  if (!Number.isNaN(at) && pool.length) {
    return pool.reduce((best, note) => Math.abs(Date.parse(note.at) - at) < Math.abs(Date.parse(best.at) - at) ? note : best).messageId
  }
  return [...pool].reverse().find((note) => note.role === 'customer')?.messageId ?? messageId
}
const ROLE = { operator: '客服', assistant: '智能助手', system: '系统' } as const

/** 对话回放（全景方案 4.5，风险页反馈 4）：情绪曲线 + 服务轴 + 完整消息流，悬停/聚焦消息高亮音符，点击音符滚到消息。 */
export const ConversationReplay = forwardRef<ReplayHandle, {
  conversationIds: string[]
  primaryId: string | null
  alias: string
}>(function ConversationReplay({ conversationIds, primaryId, alias }, ref) {
  const [current, setCurrent] = useState(primaryId ?? conversationIds[0] ?? null)
  const [scores, setScores] = useState<Record<string, ServiceScoreView>>({})
  const [error, setError] = useState('')
  const [active, setActive] = useState<string | null>(null)
  const list = useRef<HTMLOListElement>(null)
  const pendingFocus = useRef<{ messageId: string; hint?: FocusHint } | null>(null)
  const load = useCallback((id: string) => {
    setError('')
    deskApi.conversationScore(id).then((score) => setScores((old) => ({ ...old, [id]: score })))
      .catch((err) => setError((err as Error).message))
  }, [])
  const idsKey = conversationIds.join('|')
  useEffect(() => { idsKey.split('|').filter(Boolean).forEach(load) }, [idsKey, load])
  const score = current ? scores[current] : undefined
  const scrollTo = useCallback((messageId: string) => {
    const node = list.current?.querySelector<HTMLElement>(`[data-mid="${CSS.escape(messageId)}"]`)
    if (!node) return false
    node.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
    node.focus({ preventScroll: true })
    setActive(messageId)
    node.classList.add('is-flash')
    window.setTimeout(() => node.classList.remove('is-flash'), 2000)
    return true
  }, [])
  useImperativeHandle(ref, () => ({
    focus: (conversationId, messageId, hint) => {
      if ((conversationId && conversationId !== current) || !score) {
        pendingFocus.current = { messageId, hint }
        if (conversationId && conversationId !== current) setCurrent(conversationId)
        return
      }
      scrollTo(resolveFocusMessage(score.notes, messageId, hint))
    },
  }), [current, score, scrollTo])
  useEffect(() => {
    const pending = pendingFocus.current
    if (score && pending && scrollTo(resolveFocusMessage(score.notes, pending.messageId, pending.hint))) pendingFocus.current = null
  }, [score, scrollTo])
  return <div className="yt-replay">
    {conversationIds.length > 1 && <div className="yt-replay-convs" role="tablist" aria-label="关联会话">
      {conversationIds.map((id) => {
        const notes = scores[id]?.notes.filter((note) => note.role === 'customer' && note.level) ?? []
        return <button key={id} type="button" role="tab" aria-selected={id === current} className={id === current ? 'on' : undefined}
          onClick={() => setCurrent(id)}>
          <EmotionSwatch size="sm" bands={notes.map((note) => note.level!)} />
          <span>{scores[id]?.notes[0] ? `${shMonthDay(scores[id].notes[0].at)} ${shHourMinute(scores[id].notes[0].at)}` : id}</span>
        </button>
      })}
    </div>}
    {error && <Alert type="error" showIcon title={error} action={<Button size="small" onClick={() => current && load(current)}>重试</Button>} />}
    {!score && !error && <Skeleton active paragraph={{ rows: 5 }} />}
    {score && (score.notes.length === 0 ? <p className="yt-empty">暂无消息</p> : <>
      <EmotionReplay score={score} activeId={active} onPick={(id) => scrollTo(id)} />
      <ol className="yt-replay-msgs" ref={list} aria-label="消息">
        {score.notes.map((note) => {
          if (note.role === 'system') return <li key={note.messageId} data-mid={note.messageId} tabIndex={-1} className="yt-rm is-sys"><span>{note.body}</span></li>
          const customer = note.role === 'customer'
          return <li key={note.messageId} data-mid={note.messageId} tabIndex={0}
            className={`yt-rm ${customer ? 'is-c' : note.role === 'assistant' ? 'is-a' : 'is-o'}${note.messageId === active ? ' is-on' : ''}`}
            onMouseEnter={() => setActive(note.messageId)} onFocus={() => setActive(note.messageId)}>
            <div className="who"><span className="t">{shHourMinute(note.at)}</span>
              {customer ? alias : ROLE[note.role as keyof typeof ROLE]}
              {customer && note.level && <span className={`e is-${note.level}`}><i />{SWATCH_LABEL[note.level]}</span>}
              {(note.signals ?? []).map((signal) => <span key={signal} className="yt-rm-sig">{serviceRiskTypeLabels[signal]}</span>)}
            </div>
            <div className="bb">{customer ? <HighlightedText text={note.body} highlights={note.highlights} /> : note.body}</div>
          </li>
        })}
      </ol>
    </>)}
  </div>
})
