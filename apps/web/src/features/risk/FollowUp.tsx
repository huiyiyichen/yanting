import { ClockCircleOutlined } from '@ant-design/icons'
import { Button, DatePicker, Input, Modal, message } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import { useState } from 'react'
import { ApiError, deskApi, type RiskIncidentDetailView, type RiskIncidentView } from '../../api/client'

const label = (iso: string) => dayjs(iso).format('MM/DD HH:mm')

/** 下次跟进：到期标红（用户反馈 10-18 #7 修订）。 */
export function FollowUpChip({ incident }: { incident: RiskIncidentView }) {
  if (!incident.followUpAt) return null
  return <span className={`yt-follow-chip${incident.followUpDue ? ' is-due' : ''}`}>
    <ClockCircleOutlined />{incident.followUpDue ? `跟进到期 ${label(incident.followUpAt)}` : `下次跟进 ${label(incident.followUpAt)}`}</span>
}

/** 约定跟进：必填时间与备注，只记录不改状态。 */
export function FollowUpButton({ incident, onSaved }: { incident: RiskIncidentView; onSaved: (detail: RiskIncidentDetailView) => void }) {
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState<Dayjs | null>(null)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [toast, holder] = message.useMessage()
  const save = async () => {
    if (!at || !note.trim()) return
    setSaving(true)
    try {
      onSaved(await deskApi.followUpRisk(incident.incidentId, at.toISOString(), note.trim(), incident.version))
      setOpen(false); void toast.success('已约定跟进')
    } catch (err) {
      void toast.error(err instanceof ApiError && err.isConflict ? '风险已更新，请刷新后重试' : (err as Error).message)
    } finally { setSaving(false) }
  }
  return <>{holder}
    <Button icon={<ClockCircleOutlined />} onClick={() => { setAt(dayjs().add(1, 'day').hour(10).minute(0).second(0)); setNote(''); setOpen(true) }}>约定跟进</Button>
    <Modal title="约定跟进" open={open} okText="保存" cancelText="取消" confirmLoading={saving}
      okButtonProps={{ disabled: !at || !note.trim() }} onOk={() => void save()} onCancel={() => setOpen(false)} destroyOnHidden>
      <div className="yt-follow-form">
        <DatePicker showTime={{ format: 'HH:mm' }} format="MM/DD HH:mm" value={at} onChange={setAt} aria-label="跟进时间"
          disabledDate={(d) => d.isBefore(dayjs(), 'day')} style={{ width: '100%' }} />
        <Input.TextArea aria-label="跟进备注" autoSize={{ minRows: 2, maxRows: 4 }} maxLength={200} value={note}
          placeholder="约客户明早回电" onChange={(e) => setNote(e.target.value)} />
      </div>
    </Modal>
  </>
}
