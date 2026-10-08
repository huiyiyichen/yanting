import {
  AlertOutlined, BookOutlined, CustomerServiceOutlined, FileTextOutlined,
  MessageOutlined, SettingOutlined, CodeOutlined,
} from '@ant-design/icons'
import { Tooltip } from 'antd'
import { Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { CustomerView } from './pages/CustomerView'
import { SupportWorkbench } from './pages/SupportWorkbench'
import { RiskDashboardPage } from './pages/RiskDashboardPage'
import { WorkOrderPage } from './pages/WorkOrderPage'
import { KnowledgePage } from './pages/PlatformPages'
import { PromptTemplatePage } from './pages/PromptTemplatePage'
import { ModelConfigPage } from './pages/ModelConfigPage'

const navigation = [
  { path: '/customer', label: '客户视角', icon: <MessageOutlined /> },
  { path: '/support', label: '客服工作台', icon: <CustomerServiceOutlined /> },
  { path: '/risk', label: '风险预警', icon: <AlertOutlined /> },
  { path: '/platform/work-orders', label: '工单管理', icon: <FileTextOutlined /> },
  { path: '/platform/knowledge', label: '知识库', icon: <BookOutlined /> },
  { path: '/platform/prompts', label: 'Prompt 管理', icon: <CodeOutlined /> },
  { path: '/platform/models', label: '模型配置', icon: <SettingOutlined /> },
]

export function App() {
  return <div className="anker-shell desk-shell">
    <nav className="desk-nav" aria-label="主导航">
      <div className="desk-brand"><span className="desk-logo">YT</span><strong>颜听</strong></div>
      {navigation.map((item, index) => <Tooltip title={item.label} placement="right" key={item.path}>
        <NavLink to={item.path} aria-label={item.label}
          className={({ isActive }) => `desk-nav-item${isActive ? ' active' : ''}${index === 4 ? ' section-start' : ''}`}>
          {item.icon}<span>{item.label}</span>
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
}
