import { MessageOutlined } from '@ant-design/icons'
import { Button, Tag } from 'antd'
import { useMemo, useState } from 'react'
import type {
  RiskEmotionComparisonView,
  RiskEmotionView,
  RiskServicePointView,
} from '../../api/client'
import { dateLabel } from './shared'

const emotionLabels: Record<RiskEmotionView['emotion'], string> = {
  calm: '平稳',
  dissatisfied: '不满',
  angry: '激烈',
}

const emotionColors: Record<RiskEmotionView['emotion'], string> = {
  calm: '#52c41a',
  dissatisfied: '#faad14',
  angry: '#ff4d4f',
}

const emotionScore: Record<RiskEmotionView['emotion'], number> = {
  calm: 0,
  dissatisfied: 1,
  angry: 2,
}

type Props = {
  history: RiskEmotionView[]
  servicePoints?: RiskServicePointView[]
  comparisons?: RiskEmotionComparisonView[]
  onOpenConversation?: (conversationId: string) => void
}

type SelectedPoint = {
  id: string
  kind: 'emotion' | 'service'
  body: string
  occurredAt: string
  conversationId: string
  label: string
  emotion?: RiskEmotionView['emotion']
  change?: string
  triggerFactors?: string[]
}

function timeValue(value: string) {
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? 0 : parsed
}

function timeText(value: string) {
  return new Date(value).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function shortText(text: string) {
  return text.length > 34 ? `${text.slice(0, 34)}…` : text
}

export function EmotionArc({
  history, servicePoints = [], comparisons = [], onOpenConversation,
}: Props) {
  const [selected, setSelected] = useState<SelectedPoint | null>(null)
  const [showComparison, setShowComparison] = useState(false)
  const width = 640
  const height = 150
  const left = 34
  const right = 614
  const top = 28
  const bottom = 106
  const orderedHistory = useMemo(
    () => [...history].sort((a, b) => timeValue(a.occurredAt) - timeValue(b.occurredAt)),
    [history],
  )
  const first = orderedHistory[0]
  const latest = orderedHistory.at(-1)
  const rangeStart = timeValue(first?.occurredAt ?? '')
  const rangeEnd = timeValue(latest?.occurredAt ?? '')
  const range = Math.max(rangeEnd - rangeStart, 1)
  const x = (value: string) => rangeEnd === rangeStart
    ? (left + right) / 2
    : left + (right - left) * (timeValue(value) - rangeStart) / range
  const y = (emotion: RiskEmotionView['emotion']) =>
    bottom - (bottom - top) * emotionScore[emotion] / 2
  const turningPoints = orderedHistory.filter((item, index) => (
    index > 0 && emotionScore[item.emotion] !== emotionScore[orderedHistory[index - 1].emotion]
  ))
  const rapidZones = orderedHistory.reduce<Array<{ start: string; end: string }>>((zones, item, index) => {
    if (index < 2) return zones
    const previous = orderedHistory[index - 1]
    const before = orderedHistory[index - 2]
    if (
      emotionScore[before.emotion] < emotionScore[previous.emotion]
      && emotionScore[previous.emotion] < emotionScore[item.emotion]
    ) {
      zones.push({ start: before.occurredAt, end: item.occurredAt })
    }
    return zones
  }, [])
  const points = orderedHistory.map((item) => `${x(item.occurredAt)},${y(item.emotion)}`).join(' ')
  const serviceMarkers = servicePoints
    .filter((point) => timeValue(point.occurredAt) >= rangeStart && timeValue(point.occurredAt) <= rangeEnd)
    .sort((a, b) => timeValue(a.occurredAt) - timeValue(b.occurredAt))

  if (!orderedHistory.length) return null

  const selectEmotion = (point: RiskEmotionView) => {
    const index = orderedHistory.findIndex((item) => item.messageId === point.messageId)
    const previous = index > 0 ? orderedHistory[index - 1] : null
    setSelected({
      id: point.messageId,
      kind: 'emotion',
      body: point.body,
      occurredAt: point.occurredAt,
      conversationId: point.conversationId,
      label: '消费者消息',
      emotion: point.emotion,
      triggerFactors: point.triggerFactors,
      change: previous && previous.emotion !== point.emotion
        ? `${emotionLabels[previous.emotion]} → ${emotionLabels[point.emotion]}`
        : undefined,
    })
  }

  const selectService = (point: RiskServicePointView) => {
    setSelected({
      id: point.messageId,
      kind: 'service',
      body: point.body,
      occurredAt: point.occurredAt,
      conversationId: point.conversationId,
      label: point.senderRole === 'assistant' ? 'AI回复' : '客服回复',
    })
  }
  const comparison = comparisons[0]
  const comparisonPoints = comparison?.points ?? []
  const comparisonCoordinates = comparisonPoints.map((item, index) => {
    const cx = comparisonPoints.length === 1
      ? (left + right) / 2
      : left + (right - left) * index / (comparisonPoints.length - 1)
    return `${cx},${y(item.emotion)}`
  }).join(' ')

  return <section className="emotion-arc" aria-label="情绪弧线">
    <div className="emotion-arc-head">
      <div>
        <h3>情绪时间轴</h3>
        <span>{orderedHistory.length} 条消费者消息 · {serviceMarkers.length} 次服务介入</span>
      </div>
      {comparison && <Button size="small" type={showComparison ? 'primary' : 'default'}
        onClick={() => setShowComparison((value) => !value)}>
        {showComparison ? '当前进线' : '对比上次'}
      </Button>}
      <div className="emotion-arc-endpoint">
        <span style={{ background: emotionColors[latest!.emotion] }} />
        <strong>{emotionLabels[latest!.emotion]}</strong>
        <time>{dateLabel(latest!.occurredAt)}</time>
      </div>
    </div>
    <div className="emotion-arc-chart">
      <div className="emotion-arc-axis">
        <span>激烈</span>
        <span>不满</span>
        <span>平稳</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img"
        aria-label={`情绪从${emotionLabels[first!.emotion]}到${emotionLabels[latest!.emotion]}`}>
        <line x1={left} y1={top} x2={right} y2={top} className="emotion-arc-grid" />
        <line x1={left} y1={(top + bottom) / 2} x2={right} y2={(top + bottom) / 2} className="emotion-arc-grid" />
        <line x1={left} y1={bottom} x2={right} y2={bottom} className="emotion-arc-grid" />
        {rapidZones.map((zone) => <rect key={`${zone.start}-${zone.end}`}
          x={x(zone.start)} y={top - 8} width={Math.max(14, x(zone.end) - x(zone.start))}
          height={bottom - top + 16} className="emotion-arc-rapid-zone" />)}
        {showComparison && comparisonPoints.length > 0 && <polyline points={comparisonCoordinates}
          className="emotion-arc-comparison-line" />}
        {serviceMarkers.map((point) => <g key={point.messageId}>
          <line x1={x(point.occurredAt)} y1={top - 8} x2={x(point.occurredAt)} y2={bottom + 8}
            className="emotion-arc-intervention" />
          <text x={x(point.occurredAt)} y={top - 12} textAnchor="middle"
            className="emotion-arc-intervention-label">介入</text>
          <circle cx={x(point.occurredAt)} cy={bottom + 8} r={3} className="emotion-arc-service-point"
            onClick={() => selectService(point)}>
            <title>{`${timeText(point.occurredAt)} ${point.senderRole === 'assistant' ? 'AI回复' : '客服回复'}`}</title>
          </circle>
        </g>)}
        {orderedHistory.length > 1 && <polyline points={points} className="emotion-arc-line" />}
        {orderedHistory.map((item, index) => <circle key={item.messageId}
          cx={x(item.occurredAt)} cy={y(item.emotion)} r={item.messageId === selected?.id ? 6 : 4.5}
          fill={emotionColors[item.emotion]} className="emotion-arc-point"
          onClick={() => selectEmotion(item)}>
          <title>{`${timeText(item.occurredAt)} ${emotionLabels[item.emotion]}${turningPoints.some((point) => point.messageId === item.messageId) ? ` · ${emotionLabels[orderedHistory[index - 1].emotion]} → ${emotionLabels[item.emotion]}` : ''} · ${shortText(item.body)}`}</title>
        </circle>)}
      </svg>
    </div>
    <div className="emotion-arc-foot">
      <span>起点：{emotionLabels[first!.emotion]}</span>
      {turningPoints.length > 0
        ? <span className="emotion-arc-turn">转折 {turningPoints.length} 次</span>
        : <span>状态持续</span>}
      <span>当前：{emotionLabels[latest!.emotion]}</span>
    </div>
    {selected && <div className="emotion-arc-selected">
      <div className="emotion-arc-selected-head">
        <strong>{selected.label} · {timeText(selected.occurredAt)}</strong>
        {selected.emotion && <span style={{ color: emotionColors[selected.emotion] }}>
          {selected.change ?? emotionLabels[selected.emotion]}
        </span>}
      </div>
      <p>{selected.body}</p>
      {selected.triggerFactors?.map((factor) => <Tag key={factor} color="processing">{factor}</Tag>)}
      {onOpenConversation && <Button size="small" icon={<MessageOutlined />}
        onClick={() => onOpenConversation(selected.conversationId)}>打开会话</Button>}
    </div>}
  </section>
}
