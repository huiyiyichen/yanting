import { SearchOutlined } from '@ant-design/icons'
import { Empty, Input, Segmented } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import type { ReceptionItem } from '../../api/client'
import { QueueRow } from './QueueRow'

const MODES = ['全部', '人工', '风险', '未读'] as const
const hasRisk = (item: ReceptionItem) => Boolean(item.activeRiskTypes?.length || item.reviewRiskTypes?.length)

/** 左侧接待队列：搜索、筛选与等待时钟都收在这里，时钟跳动不再重渲整个工作台。 */
export function ReceptionQueue({ items, activeId, onOpen }: {
  items: ReceptionItem[]
  activeId: string | null
  onOpen: (conversationId: string) => void
}) {
  const [mode, setMode] = useState<string>('全部')
  const [query, setQuery] = useState('')
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 30000); return () => window.clearInterval(timer) }, [])
  const visible = useMemo(() => items.filter((item) =>
    (mode !== '未读' || item.unreadCount > 0)
    && (mode !== '人工' || item.serviceMode === 'operator_assisted')
    && (mode !== '风险' || hasRisk(item))
    && `${item.buyerAlias} ${item.conversationId} ${item.preview}`.includes(query)), [items, mode, query])
  const counts: Record<string, number> = useMemo(() => ({
    人工: items.filter((item) => item.serviceMode === 'operator_assisted').length,
    风险: items.filter(hasRisk).length,
  }), [items])
  return <div className="reception-queue">
    <div className="reception-queue-head">
      <Input variant="filled" prefix={<SearchOutlined />} placeholder="客户、订单号、聊天记录" aria-label="搜索会话" value={query} allowClear onChange={(e) => setQuery(e.target.value)} />
      <Segmented className="yt-qtabs" options={MODES.map((value) => ({ value,
        label: <>{value}{counts[value] ? <span className="n">{counts[value]}</span> : null}</> }))} value={mode} onChange={setMode} />
    </div>
    <div className="reception-list">{visible.length ? <div className="yt-queue-group"><span>正在接待</span><span>最近消息</span></div> : null}
      {visible.map((item) => <QueueRow key={item.conversationId} item={item} active={activeId === item.conversationId} now={now} onOpen={onOpen} />)}
      {!visible.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" />}
    </div>
  </div>
}
