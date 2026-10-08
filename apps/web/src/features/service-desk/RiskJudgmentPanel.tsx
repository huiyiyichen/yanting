import { AuditOutlined } from '@ant-design/icons'
import { Button, Collapse, Empty, Input, Modal, Segmented, Space, Tag, message } from 'antd'
import { useEffect, useRef, useState } from 'react'
import { ApiError, deskApi, type RiskIncidentDetailView, type RiskJudgmentRequest } from '../../api/client'
import { serviceRiskTypeLabels } from '../../contracts/enums'
import { dateLabel } from './shared'

export const judgmentLabels = {
  confirmed: '确认风险', false_positive: '误报', insufficient: '信息不足',
} as const

type Target = {
  incidentId: string
  alertId: string
  title: string
  expectedVersion: string
  expectedJudgmentId: string | null
  triggerSummary: string
  evidence: { label: string; body: string; occurredAt?: string | null }[]
}

export function RiskJudgmentPanel({ detail, onChange }: {
  detail: RiskIncidentDetailView
  onChange: (next: RiskIncidentDetailView) => void
}) {
  const [target, setTarget] = useState<Target | null>(null)
  const [verdict, setVerdict] = useState<RiskJudgmentRequest['verdict']>('confirmed')
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [toast, holder] = message.useMessage()
  const active = useRef(true)
  useEffect(() => {
    active.current = true
    return () => { active.current = false }
  }, [])
  const save = async () => {
    if (!target || saving || !note.trim()) return
    setSaving(true)
    try {
      const next = await deskApi.judgeRisk(target.incidentId, target.alertId, {
        verdict, note, expectedVersion: target.expectedVersion,
        expectedJudgmentId: target.expectedJudgmentId,
      })
      if (active.current) {
        onChange(next)
        setTarget(null)
        void toast.success('判断已记录')
      }
    } catch (err) {
      if (active.current) {
        void toast.error((err as Error).message)
        if (err instanceof ApiError && err.isConflict) {
          setTarget(null)
          try {
            const next = await deskApi.risk(target.incidentId)
            if (active.current) onChange(next)
          } catch (refreshError) {
            if (active.current) void toast.error((refreshError as Error).message)
          }
        }
      }
    } finally { if (active.current) setSaving(false) }
  }
  return <>{holder}
    {detail.incident.signals.map((signal) => {
      const latest = detail.incident.judgments?.find((item) => item.alertId === signal.alertId)
      const title = serviceRiskTypeLabels[signal.riskType]
      return <section className="service-section" key={signal.alertId}>
        <div className="section-title-row"><h3>{title}</h3><Space wrap>
          <Tag>第 {signal.episode ?? 1} 轮</Tag>
          <Tag>{latest ? judgmentLabels[latest.verdict] : '未判断'}</Tag>
          {latest?.stale && <Tag color="warning">待重审</Tag>}
        </Space></div>
        <p>{signal.triggerSummary}</p>
        {latest && <><p>{latest.note}</p><p>{latest.actor} · {dateLabel(latest.createdAt)}</p></>}
        <Button data-testid={`risk-judge-${signal.alertId}`} icon={<AuditOutlined />} onClick={() => {
          setTarget({
            incidentId: detail.incident.incidentId, alertId: signal.alertId, title,
            expectedVersion: detail.incident.version ?? '',
            expectedJudgmentId: latest?.judgmentId ?? null,
            triggerSummary: signal.triggerSummary,
            evidence: detail.evidence.filter((item) => signal.evidenceRefs.includes(item.ref)),
          })
          setVerdict(latest?.verdict ?? 'confirmed')
          setNote('')
        }}>记录复核</Button>
      </section>
    })}
    <section className="service-section"><h3>判断记录</h3>
      {detail.judgmentHistory?.length ? detail.judgmentHistory.map((item) => <div className="breakpoint-finding" key={item.judgmentId}>
        <div className="section-title-row"><strong>{serviceRiskTypeLabels[item.riskType as keyof typeof serviceRiskTypeLabels] ?? item.riskType}</strong>
          <Space wrap><Tag>第 {item.episode} 轮</Tag><Tag>{judgmentLabels[item.verdict]}</Tag>{item.stale && <Tag color="warning">依据已变化</Tag>}</Space>
        </div>
        <p>{item.note}</p><p>{item.actor} · {dateLabel(item.createdAt)}</p>
        <Collapse size="small" items={[{ key: 'snapshot', label: '证据快照', children: <>
          <p>{item.triggerSummary}</p>
          {item.evidence?.map((evidence) => <blockquote className="evidence-quote" key={evidence.ref}>
            <small>{evidence.label} · {dateLabel(evidence.occurredAt)}</small><p>{evidence.body}</p>
          </blockquote>)}
        </> }]} />
      </div>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无判断记录：当前信号还没有人工确认结果" />}
    </section>
    <Modal title={target ? `判断复核 · ${target.title}` : '判断复核'} open={Boolean(target)}
      onCancel={() => { if (!saving) setTarget(null) }} onOk={() => void save()}
      okText="保存判断" cancelText="取消" confirmLoading={saving}
      cancelButtonProps={{ disabled: saving }} okButtonProps={{ disabled: !note.trim() }}>
      <Space orientation="vertical" style={{ width: '100%' }} size="middle">
        <Segmented aria-label="风险判断" value={verdict}
          onChange={(value) => setVerdict(value as RiskJudgmentRequest['verdict'])}
          options={Object.entries(judgmentLabels).map(([value, label]) => ({ value, label }))} />
        {target && <section className="service-section">
          <strong>当前信号</strong><p>{target.triggerSummary}</p>
          {target.evidence.length ? <blockquote className="evidence-quote">
            <small>触发证据</small>
            {target.evidence.slice(0, 3).map((item) => <p key={`${item.label}-${item.body}`}>{item.body}</p>)}
          </blockquote> : <Tag>暂无可展示原文</Tag>}
        </section>}
        <Input.TextArea aria-label="判断依据" placeholder="判断依据" rows={4} maxLength={2000}
          value={note} onChange={(event) => setNote(event.target.value)} />
      </Space>
    </Modal>
  </>
}
