import { UserOutlined } from '@ant-design/icons'
import { Select, Tooltip } from 'antd'
import { useEffect, useState } from 'react'
import { deskApi, type DemoOperatorRosterView } from '../../api/client'
import { getDemoOperator, setDemoOperator, useDemoOperator } from './operator'

export function DemoOperatorSelect() {
  const operator = useDemoOperator()
  const [roster, setRoster] = useState<DemoOperatorRosterView | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void deskApi.operators().then((data) => {
      if (!Array.isArray(data.operators) || !data.operators.length) throw new Error('身份服务不可用')
      if (active) {
        if (!data.operators.some((item) => item.operatorId === getDemoOperator())) setDemoOperator(data.defaultOperatorId)
        setRoster(data)
      }
    })
      .catch(() => { if (active) setError('身份服务不可用') })
    return () => { active = false }
  }, [])
  return <Tooltip title={error || undefined}><div className="desk-operator">
    <UserOutlined />
    <Select aria-label="模拟客服" value={roster ? operator : undefined}
      placeholder={error || '模拟客服'} loading={!roster && !error} disabled={!roster}
      options={roster?.operators.map((item) => ({ value: item.operatorId, label: item.name }))}
      onChange={setDemoOperator} />
  </div></Tooltip>
}
