import { Badge } from 'antd'
import type { ReactNode } from 'react'
import { DemoOperatorSelect } from '../features/service-desk/DemoOperatorSelect'

export function QianniuTopbar({ title, stats, actions }: {
  title: string
  stats?: { label: string; value: number | string; warning?: boolean }[]
  actions?: ReactNode
}) {
  return <header className="desk-topbar">
    <div className="desk-topbar-title"><h1>{title}</h1><Badge status="processing" /></div>
    <div className="desk-topbar-stats">
      {stats?.map((stat) => <div key={stat.label} className={stat.warning ? 'is-warning' : ''}>
        <span>{stat.label}</span><strong>{stat.value}</strong>
      </div>)}
    </div>
    <div className="desk-topbar-actions"><DemoOperatorSelect />{actions}</div>
  </header>
}
