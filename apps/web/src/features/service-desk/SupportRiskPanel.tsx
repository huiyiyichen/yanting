import { CustomerServiceOutlined, ReloadOutlined } from '@ant-design/icons'
import { Alert, Button, Spin, Tooltip } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { deskApi, type ReceptionItem, type RiskIncidentView } from '../../api/client'
import { serviceRiskTypeLabels } from '../../contracts/enums'
import { dateLabel } from './shared'
import { followupDeadlines, signalAttention } from './riskPresentation'
import { visibleInterval } from '../../hooks/visibleInterval'

function isOpen(signal: RiskIncidentView['signals'][number]) {
  return ['active', 'review'].includes(signalAttention(signal))
}

function signalState(signal: RiskIncidentView['signals'][number]) {
  if (signal.conditions?.analysisStale) return '依据待更新'
  if (signal.signalActive === false) return '待复核'
  return signal.riskStatus === 'in_progress' ? '处理中' : '待介入'
}

function nextAction(signal: RiskIncidentView['signals'][number]) {
  if (signal.conditions?.analysisStale) return '核对最新反馈并更新断点分析'
  if (signal.signalActive === false) return '核对最新反馈与处理结果，确认后关闭'
  if (signal.riskStatus === 'in_progress' && signal.riskType === 'response_wait') return '继续回复消费者当前问题'
  return signal.recommendedAction
}

const riskLevelLabels: Record<string, string> = { high: '高风险', medium: '中风险', low: '低风险', unknown: '未知风险' }

export function SupportRiskPanel({ conversationId, enabled, refreshKey, serviceMode, onIntervened }: {
  conversationId: string
  enabled: boolean
  refreshKey: string
  serviceMode?: ReceptionItem['serviceMode']
  onIntervened?: (conversationId: string) => Promise<void>
}) {
  const [result, setResult] = useState<{ conversationId: string; rows: RiskIncidentView[] } | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [takingOver, setTakingOver] = useState<string | null>(null)
  const [actionError, setActionError] = useState('')
  const active = useRef(conversationId)
  active.current = conversationId
  const requestVersion = useRef(0)
  const mounted = useRef(true)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  useEffect(() => {
    if (!enabled) return
    let disposed = false
    let running = false
    const load = async () => {
      if (running || document.hidden) return
      running = true
      const request = ++requestVersion.current
      setLoading(true)
      try {
        const rows = await deskApi.conversationRisks(conversationId)
        if (rows.some((incident) => !incident.currentAction)) {
          throw new Error('后端风险接口版本过旧')
        }
        if (!disposed && request === requestVersion.current) {
          setResult({ conversationId, rows })
          setError('')
        }
      } catch (err) {
        if (!disposed && request === requestVersion.current) setError((err as Error).message)
      } finally {
        running = false
        if (!disposed) setLoading(false)
      }
    }
    void load()
    const stop = visibleInterval(() => void load(), 10000)
    const focus = () => { void load() }
    window.addEventListener('focus', focus)
    return () => {
      disposed = true
      stop()
      window.removeEventListener('focus', focus)
    }
  }, [conversationId, enabled, refreshKey, retry])

  const currentRows = result?.conversationId === conversationId ? result.rows.filter((incident) =>
    ['intervene', 'review'].includes(incident.currentAction)
    && ['pending', 'in_progress'].includes(incident.riskStatus)
    && incident.signals.some(isOpen)) : []
  const byType = new Map<string, { incident: RiskIncidentView; signal: RiskIncidentView['signals'][number] }>()
  for (const incident of currentRows) {
    for (const signal of incident.signals) {
      if (signal.conversationId !== conversationId || !isOpen(signal)) continue
      const previous = byType.get(signal.riskType)
      if (!previous || (signalAttention(previous.signal) === 'review' && signalAttention(signal) === 'active')
        || (signalAttention(previous.signal) === signalAttention(signal)
          && signal.updatedAt > previous.signal.updatedAt)) {
        byType.set(signal.riskType, { incident, signal })
      }
    }
  }
  const rows = [...new Set([...byType.values()].map(({ incident }) => incident))].map((incident) => ({
    ...incident, signals: [...byType.values()].filter((entry) => entry.incident === incident).map((entry) => entry.signal),
  }))
  const takeOver = async (incident: RiskIncidentView) => {
    if (takingOver || loading || error) return
    const target = conversationId
    setTakingOver(incident.incidentId)
    setActionError('')
    try {
      const detail = await deskApi.interveneRisk(incident.incidentId, target, incident.version)
      if (!mounted.current || active.current !== target) return
      requestVersion.current++
      setResult((current) => current?.conversationId === target ? {
        ...current, rows: current.rows.map((row) => row.incidentId === incident.incidentId ? detail.incident : row),
      } : { conversationId: target, rows: [detail.incident] })
      setRetry((value) => value + 1)
      await onIntervened?.(target)
    } catch (err) {
      if (mounted.current && active.current === target) setActionError((err as Error).message)
    } finally {
      if (mounted.current && active.current === target) setTakingOver(null)
    }
  }
  const pending = rows.reduce((sum, incident) => sum + incident.signals.length, 0)
  const canTakeOver = (incident: RiskIncidentView) => incident.serviceState === 'live' && incident.signals.some((signal) =>
    signalAttention(signal) === 'active' && (signal.riskStatus === 'pending' || serviceMode !== 'operator_assisted'))
  return <section className="service-section yt-card yt-risk-focus" aria-label="当前风险关注">
    <h3>风险关注
      <span className="r">
        {loading ? <Spin size="small" /> : pending ? `${pending} 项待处理` : null}
        <Tooltip title="刷新风险关注">
          <Button type="text" size="small" aria-label="刷新风险关注" icon={<ReloadOutlined />}
            loading={loading} onClick={() => setRetry((value) => value + 1)} />
        </Tooltip>
      </span>
    </h3>
    {error && <Alert type="error" showIcon title={`风险读取失败：${error}`} />}
    {actionError && <Alert type="error" showIcon title={actionError} />}
    <div className="yt-risks">
      {rows.map((incident) => incident.signals.map((signal, index) => {
        const needsReview = signalAttention(signal) === 'review'
        const query = new URLSearchParams({ incident: incident.incidentId, conversation: conversationId, type: signal.riskType })
        const primary = index === 0 && canTakeOver(incident)
        return <div className={`yt-rk is-${signal.riskLevel}${needsReview ? ' is-review' : ''}`} key={signal.alertId}>
          <i className="bar" aria-hidden />
          <div className="yt-rk-main">
            <b>{serviceRiskTypeLabels[signal.riskType]}</b>
            <span className="yt-rk-quote">{signal.triggerSummary}</span>
            <small className="yt-rk-meta">
              <span>{riskLevelLabels[signal.riskLevel]}</span>
              <span>{signalState(signal)}</span>
              <span className="next-action">{nextAction(signal)}</span>
              {primary && <Link to={`/risk?${query}`} aria-label={`查看${serviceRiskTypeLabels[signal.riskType]}处置详情`}>详情</Link>}
            </small>
            {signal.riskType === 'followup_due_soon' ? followupDeadlines(signal.conditions).map((deadline) => (
              <small className="yt-rk-meta" key={`${deadline.ticketId}-${deadline.dueAt}`}>
                <Link to={`/platform/work-orders?ticket=${encodeURIComponent(deadline.ticketId)}`}>{deadline.ticketId}</Link>
                <span>截止 {dateLabel(deadline.dueAt)}</span>
              </small>
            )) : null}
          </div>
          {primary ? <Button size="small" type="primary" icon={<CustomerServiceOutlined />}
            loading={takingOver === incident.incidentId}
            disabled={Boolean(error) || loading || Boolean(takingOver && takingOver !== incident.incidentId)}
            aria-label={serviceMode === 'operator_assisted' ? '开始处理' : '接管会话'}
            onClick={() => void takeOver(incident)}>{serviceMode === 'operator_assisted' ? '开始处理' : '接管处理'}</Button>
            : <Link className="yt-rk-link" to={`/risk?${query}`}
              aria-label={`查看${serviceRiskTypeLabels[signal.riskType]}处置详情`}>详情</Link>}
        </div>
      }))}
      {!error && !loading && !rows.length ? <p className="yt-empty">暂无待处理风险</p> : null}
    </div>
  </section>
}
