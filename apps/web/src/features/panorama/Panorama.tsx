import { Alert, message } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { supportApi, type MessageView, type PanoramaView } from '../../api/client'
import { visibleInterval } from '../../hooks/visibleInterval'
import { PanoramaPreview } from './PanoramaPreview'
import { PanoramaWall } from './PanoramaWall'
import { isLate, type PanoramaFilter } from './panoramaModel'
import { PanoramaDemo } from './demoEngine'

const DEMO_KEY = 'yt-pano-demo'

/** AI 接待全景：轮询全景接口（页面隐藏暂停），可手动暂停刷新；接管复用服务模式接口。 */
export function Panorama({ onOpen }: { onOpen: (conversationId: string) => void }) {
  const [view, setView] = useState<PanoramaView | null>(null)
  const [error, setError] = useState('')
  const [live, setLive] = useState(true)
  const [filter, setFilter] = useState<PanoramaFilter>('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [messages, setMessages] = useState<MessageView[]>([])
  const [now, setNow] = useState(() => Date.now())
  const [busy, setBusy] = useState(false)
  const [toast, holder] = message.useMessage()
  const [demo, setDemo] = useState(() => localStorage.getItem(DEMO_KEY) === '1')
  const engine = useRef<PanoramaDemo | null>(null)
  const [demoView, setDemoView] = useState<PanoramaView | null>(null)
  const [demoTick, setDemoTick] = useState(0)
  useEffect(() => {
    localStorage.setItem(DEMO_KEY, demo ? '1' : '0')
    if (!demo) { engine.current = null; setDemoView(null); return }
    const sim = engine.current ??= new PanoramaDemo()
    setDemoView(sim.view()); setNow(sim.now()); setSelectedId((id) => id ?? 'S00059')
    if (!live) return
    let last = performance.now()
    const timer = window.setInterval(() => {
      const t = performance.now()
      sim.tick(Math.min(500, t - last)); last = t
      setDemoView(sim.view()); setNow(sim.now()); setDemoTick((n) => n + 1)
    }, 200)
    return () => window.clearInterval(timer)
  }, [demo, live])
  const load = useCallback(async () => {
    try { setView(await supportApi.panorama()); setError('') } catch (err) { setError((err as Error).message) }
  }, [])
  useEffect(() => {
    if (!live || demo) return
    void load()
    return visibleInterval(() => void load(), 1500)
  }, [live, demo, load])
  useEffect(() => demo ? undefined : visibleInterval(() => setNow(Date.now()), 1000), [demo])
  const shown = demo ? demoView : view
  const items = shown?.items ?? []
  const selected = items.find((item) => item.conversationId === selectedId) ?? null
  const revision = selected ? `${selected.lastActivityAt}|${selected.lane}` : ''
  useEffect(() => {
    if (!selectedId || !revision) { setMessages([]); return }
    if (demo) { setMessages(engine.current?.messages(selectedId) ?? []); return }
    let cancelled = false
    supportApi.receptionMessages(selectedId).then((rows) => { if (!cancelled) setMessages(rows) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [selectedId, revision, demo, demoTick])
  const takeover = async (id: string) => {
    if (demo) { engine.current?.takeover(id); setDemoView(engine.current?.view() ?? null); return }
    setBusy(true)
    try { await supportApi.setReceptionMode(id, 'operator_assisted'); await load() }
    catch (err) { void toast.error((err as Error).message) } finally { setBusy(false) }
  }
  const risky = items.filter((item) => item.highRisk).length
  const late = items.filter((item) => isLate(item, now)).length
  return <div className="yt-pano">{holder}
    <div className="yt-pano-main">
      <div className="yt-pano-tools">
        <div className="yt-pano-filter" role="radiogroup" aria-label="全景筛选">
          {([['all', '全部'], ['risk', `有风险 ${risky}`], ['late', `等待超时 ${late}`]] as const).map(([key, label]) =>
            <button key={key} type="button" role="radio" aria-checked={filter === key} className={filter === key ? 'on' : undefined}
              onClick={() => setFilter(key)}>{label}</button>)}
        </div>
        <div className="yt-pano-legend" aria-label="图例">
          <span><i className="is-calm" />平稳</span><span><i className="is-dissatisfied" />不满</span><span><i className="is-angry" />激烈</span>
          <span><span className="yt-wave is-on" aria-hidden="true"><i /><i /><i /><i /><i /></span>AI 处理中</span>
          <span><i className="is-risk" />高风险</span>
        </div>
        <button type="button" className={`yt-pano-demo${demo ? ' is-on' : ''}`} aria-pressed={demo} onClick={() => setDemo((v) => !v)}>演示</button>
        <button type="button" className={`yt-pano-live${live ? ' is-on' : ''}`} aria-pressed={live} onClick={() => setLive((v) => !v)}>
          <i />{live ? '实时' : '已暂停'}</button>
      </div>
      {error && <Alert type="error" title={error} showIcon />}
      <PanoramaWall items={items} now={now} filter={filter} selectedId={selectedId}
        running={shown?.running ?? 0} queued={shown?.queued ?? 0} windowMinutes={shown?.activeWindowMinutes}
        onSelect={setSelectedId} />
    </div>
    <PanoramaPreview item={selected} messages={messages} now={now} busy={busy} onTakeover={(id) => void takeover(id)} onOpen={demo ? undefined : onOpen} />
  </div>
}
