import type { ReactNode } from 'react'
import { DemoOperatorSelect } from '../features/service-desk/DemoOperatorSelect'

/** 所有业务页统一页头：标题、可选范围切换、指标、操作区（含演示客服切换）。 */
export function PageHeader({ title, stats, actions, extra }: {
  title: string
  extra?: ReactNode
  stats?: { label: string; value: number | string; warning?: boolean }[]
  actions?: ReactNode
}) {
  return <header className="desk-topbar">
    <div className="desk-topbar-title"><h1>{title}</h1>{extra}</div>
    <div className="desk-topbar-stats">
      {stats?.map((stat) => <div key={stat.label} className={stat.warning ? 'is-warning' : ''}>
        <span>{stat.label}</span><strong>{stat.value}</strong>
      </div>)}
    </div>
    <div className="desk-topbar-actions"><DemoOperatorSelect />{actions}</div>
  </header>
}
