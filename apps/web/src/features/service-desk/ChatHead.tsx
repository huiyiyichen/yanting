import { CustomerServiceOutlined, FileTextOutlined, ReloadOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons'
import { Avatar, Button, Popconfirm, Segmented, Tag, Tooltip } from 'antd'
import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { ReceptionItem } from '../../api/client'
import { emotionLevelLabels, serviceRiskTypeLabels } from '../../contracts/enums'
import { riskHref } from './QueueRow'

type Mode = 'autonomous' | 'operator_assisted'
const emotionColors: Record<string, string> = { calm: 'success', dissatisfied: 'warning', angry: 'error' }

/** 聊天头部：一行内放买家、情绪、风险、接待方式切换与操作。 */
export function ChatHead({ item, switching, onMode, onTicket, onRefresh, leading, trailing }: {
  item?: ReceptionItem
  switching: boolean
  onMode: (mode: Mode) => void
  onTicket: () => void
  onRefresh: () => void
  leading?: ReactNode
  trailing?: ReactNode
}) {
  const [confirming, setConfirming] = useState(false)
  const automatic = item?.serviceMode === 'autonomous'
  return <header className="anker-chat-head anker-hairline-bottom yt-chat-head">
    {leading}
    <Avatar icon={<UserOutlined />} /><strong className="chat-buyer">{item?.buyerAlias ?? '未选择会话'}</strong>
    {item?.currentEmotion && <Tag color={emotionColors[item.currentEmotion]}>{emotionLevelLabels[item.currentEmotion]}</Tag>}
    {item?.riskLevel === 'high' && <Tag color="error">高风险</Tag>}
    {item?.activeRiskTypes?.map((risk) => <Link key={risk} to={riskHref(item.conversationId, risk)}
      aria-label={`查看当前${serviceRiskTypeLabels[risk]}`}><Tag color="warning">{serviceRiskTypeLabels[risk]}</Tag></Link>)}
    {item?.reviewRiskTypes?.map((risk) => <Link key={`review-${risk}`} to={riskHref(item.conversationId, risk)}
      aria-label={`复核当前${serviceRiskTypeLabels[risk]}`}><Tag color="processing">待复核 · {serviceRiskTypeLabels[risk]}</Tag></Link>)}
    {item?.handoffReason && <Tag color="warning">{item.handoffReason}</Tag>}
    <span className="yt-chat-head-actions">
      {item && <Popconfirm title="恢复 AI 自动接待？" okText="恢复" cancelText="取消" open={confirming}
        onOpenChange={(open) => { if (!open) setConfirming(false) }}
        onConfirm={() => { setConfirming(false); onMode('autonomous') }} onCancel={() => setConfirming(false)}>
        <Segmented size="small" name="reception-mode" aria-label="接待方式" disabled={switching}
          value={automatic ? 'autonomous' : 'operator_assisted'}
          options={[{ value: 'autonomous', label: 'AI' }, { value: 'operator_assisted', label: '人工' }]}
          onChange={(value) => { if (value === 'operator_assisted') onMode(value); else setConfirming(true) }} />
      </Popconfirm>}
      <Button type="text" aria-label="建工单" icon={<FileTextOutlined />} disabled={!item} onClick={onTicket}>建工单</Button>
      <Tooltip title="刷新会话"><Button type="text" aria-label="刷新会话" icon={<ReloadOutlined />} disabled={!item} onClick={onRefresh} /></Tooltip>
      {trailing}
    </span>
  </header>
}

/** AI 接待时替代输入区：状态 + 接管。 */
export function AiReceptionBar({ replying, switching, onTakeOver }: { replying: boolean; switching: boolean; onTakeOver: () => void }) {
  return <div className="yt-ai-bar">
    <RobotOutlined className="yt-ai-bar-icon" /><span>{replying ? 'AI 回复中' : 'AI 接待中'}</span>
    <i className="yt-ai-bar-sep" aria-hidden="true" />
    <Button type="link" size="small" icon={<CustomerServiceOutlined />} aria-label="接管会话" loading={switching} onClick={onTakeOver}>接管</Button>
  </div>
}
