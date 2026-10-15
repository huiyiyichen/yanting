import { ClockCircleOutlined } from '@ant-design/icons'
import { Avatar, Tag, Tooltip } from 'antd'
import type { ConsumerProfileView } from '../../api/client'
import { Voiceprint } from '../voiceprint/Voiceprint'

const EMOTION_LABEL: Record<string, string> = { calm: '平稳', dissatisfied: '不满', angry: '激烈' }
const PROMISE_STATUS: Record<string, string> = { pending: '待兑现', due: '已到期', fulfilled: '已兑现' }

/** 业务时间统一按 UTC+8 展示。 */
function hk(value: string, withTime = false): string {
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
  }).formatToParts(new Date(value))
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? ''
  return withTime ? `${get('hour')}:${get('minute')}` : `${get('month')}/${get('day')}`
}

export function PersonaCard({ profile }: { profile: ConsumerProfileView }) {
  const emotion = profile.currentEmotion ?? null
  const concerns = profile.memory.concerns.slice(0, 4)
  const rejected = profile.memory.rejected.slice(0, 3)
  return <section className="yt-persona" aria-label="客户画像">
    <header className="yt-persona-head">
      <Avatar className="yt-persona-avatar">{profile.alias.slice(0, 1)}</Avatar>
      <div className="yt-persona-id">
        <strong title={profile.alias}>{profile.alias}</strong>
        <span className="yt-persona-meta">
          <span>{profile.contacts.withinThreeDays > 1
            ? `3 天内第 ${profile.contacts.withinThreeDays} 次进线` : `进线 ${profile.contacts.total} 次`}</span>
          {profile.aggregation === 'buyer_alias' && <Tag className="yt-chip">同昵称</Tag>}
          {profile.skin && <Tooltip title={profile.skin.quote}>
            <Tag className="yt-chip" data-testid="persona-skin" title={profile.skin.quote}>{profile.skin.text}</Tag>
          </Tooltip>}
        </span>
      </div>
      {emotion && <div className={`yt-persona-emotion is-${emotion}`}>
        <strong>{EMOTION_LABEL[emotion]}</strong>
        {profile.escalatedAt && <span>{hk(profile.escalatedAt, true)} 起升级</span>}
      </div>}
    </header>
    {profile.emotionTrail.length > 0 && <Voiceprint points={profile.emotionTrail} />}
    {(concerns.length > 0 || rejected.length > 0) && <dl className="yt-mem">
      {concerns.length > 0 && <><dt id={`mem-c-${profile.conversationId}`}>关注</dt>
        <dd aria-labelledby={`mem-c-${profile.conversationId}`}>{concerns.map((item) =>
          <span key={item.text} title={item.sourceRef} className="yt-memory-tag">{item.text}</span>)}</dd></>}
      {rejected.length > 0 && <><dt id={`mem-r-${profile.conversationId}`}>已拒绝</dt>
        <dd aria-labelledby={`mem-r-${profile.conversationId}`}>{rejected.map((item) =>
          <span key={item.text} title={item.sourceRef} className="yt-memory-tag is-rejected">{item.text}</span>)}</dd></>}
    </dl>}
    {profile.promises.map((promise) => <div key={promise.sourceRef}
      className={`yt-promise is-${promise.status}`}>
      <span className="yt-promise-ic"><ClockCircleOutlined /></span>
      <div className="yt-promise-body"><b>{hk(promise.madeAt)} 客服承诺</b><span title={promise.text}>{promise.text}</span></div>
      <div className="yt-promise-due" data-testid="promise-due">{hk(promise.dueAt)}<small>{PROMISE_STATUS[promise.status] ?? promise.status}</small></div>
    </div>)}
    {profile.lastContact && <div className="yt-persona-last">
      上次 {hk(profile.lastContact.at)} · {profile.lastContact.scene || profile.lastContact.conversationId}
    </div>}
  </section>
}
