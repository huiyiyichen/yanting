import {
  AlertOutlined, BookOutlined, CustomerServiceOutlined, FileTextOutlined,
  MessageOutlined, SettingOutlined, CodeOutlined,
} from '@ant-design/icons'
import { Badge, ConfigProvider, Tooltip, theme } from 'antd'
import { useEffect, useState } from 'react'
import { deskApi } from './api/client'
import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { CustomerView } from './pages/CustomerView'
import { SupportWorkbench } from './pages/SupportWorkbench'
import { RiskDashboardPage } from './pages/RiskDashboardPage'
import { WorkOrderPage } from './pages/WorkOrderPage'
import { KnowledgePage } from './pages/PlatformPages'
import { PromptTemplatePage } from './pages/PromptTemplatePage'
import { ModelConfigPage } from './pages/ModelConfigPage'
import { visibleInterval } from './hooks/visibleInterval'
import { useTheme } from './hooks/themeMode'

const navigation = [
  { path: '/customer', label: '客户视角', short: '客户', icon: <MessageOutlined /> },
  { path: '/support', label: '客服工作台', short: '接待', icon: <CustomerServiceOutlined /> },
  { path: '/risk', label: '风险预警', short: '风险', icon: <AlertOutlined /> },
  { path: '/platform/work-orders', label: '工单管理', short: '工单', icon: <FileTextOutlined /> },
  { path: '/platform/knowledge', label: '知识库', short: '知识', icon: <BookOutlined /> },
  { path: '/platform/prompts', label: 'Prompt 管理', short: 'Prompt', icon: <CodeOutlined /> },
  { path: '/platform/models', label: '模型配置', short: '模型', icon: <SettingOutlined /> },
]

/** 声纹 Logo：五根金色竖条（高 8/16/22/12/6）。 */
function VoiceprintLogo() {
  return <svg className="yt-logo" viewBox="0 0 28 28" width={28} height={28} aria-hidden="true">
    {[8, 16, 22, 12, 6].map((h, i) => <rect key={i} x={3 + i * 5} y={14 - h / 2} width={2.6} height={h} rx={1.3} />)}
  </svg>
}

/** 风险入口徽标：当前有效的高风险事件数。 */
function useHighRiskCount(enabled: boolean) {
  const [count, setCount] = useState(0)
  useEffect(() => {
    // 客户视角不读取任何内部风险数据（AC-14）
    if (!enabled) return
    let cancelled = false
    const read = () => {
      if (document.hidden) return
      deskApi.riskOverview('live')
        .then((view) => { if (!cancelled) setCount(view?.counts?.pendingHigh ?? 0) })
        .catch(() => undefined)
    }
    read()
    const stop = visibleInterval(read, 30000)
    return () => { cancelled = true; stop() }
  }, [enabled])
  return enabled ? count : 0
}

const LIGHT_THEME = { algorithm: theme.defaultAlgorithm }
/** 深色：父级显式设了浅色容器色，需在这里覆盖，否则 darkAlgorithm 不生效（表格、输入框仍白底）。 */
const DARK_THEME = { algorithm: theme.darkAlgorithm, token: {
  colorBgContainer: '#251b2e', colorBgElevated: '#2d2238', colorBgLayout: '#1a1320', colorPrimary: '#8d6fb0', colorLink: '#d9b47c',
  colorBorder: 'rgba(236, 224, 245, 0.16)', colorBorderSecondary: 'rgba(236, 224, 245, 0.08)',
} }

export function App() {
  const { pathname } = useLocation()
  const highRisk = useHighRiskCount(!pathname.startsWith('/customer'))
  const { mode } = useTheme(pathname.startsWith('/customer'))
  return <ConfigProvider theme={mode === 'dark' ? DARK_THEME : LIGHT_THEME}>
  <div className="yt-shell desk-shell">
    <nav className="desk-nav yt-rail" aria-label="主导航">
      <div className="desk-brand"><VoiceprintLogo /><strong>颜听</strong></div>
      {navigation.map((item, index) => <Tooltip title={item.label} placement="right" key={item.path}>
        <NavLink to={item.path} aria-label={item.label}
          className={({ isActive }) => `desk-nav-item${isActive ? ' active' : ''}${index === 4 ? ' section-start' : ''}`}>
          <Badge count={item.path === '/risk' ? highRisk : 0} size="small" offset={[2, -2]}>{item.icon}</Badge>
          <span>{item.short}</span>
        </NavLink>
      </Tooltip>)}
    </nav>
    <main className="desk-main">
      <Routes>
        <Route path="/customer" element={<CustomerView />} />
        <Route path="/support" element={<SupportWorkbench />} />
        <Route path="/risk" element={<RiskDashboardPage />} />
        <Route path="/platform/work-orders" element={<WorkOrderPage />} />
        <Route path="/platform/knowledge" element={<KnowledgePage />} />
        <Route path="/platform/prompts" element={<PromptTemplatePage />} />
        <Route path="/platform/models" element={<ModelConfigPage />} />
        <Route path="*" element={<Navigate to="/support" replace />} />
      </Routes>
    </main>
  </div>
  </ConfigProvider>
}
