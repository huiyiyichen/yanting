/**
 * 应用入口。
 *
 * S0 阶段只建立可启动的最小外壳：主题、路由、左侧演示视角导航。
 * 客户视角与客服工作台的具体功能分别在 S3 按前端规范实现。
 */
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'
import { antdTheme } from './styles/theme'
import './styles/global.css'

const container = document.getElementById('root')
if (!container) {
  throw new Error('未找到 #root 挂载点')
}

createRoot(container).render(
  <StrictMode>
    <ConfigProvider locale={zhCN} theme={antdTheme}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </StrictMode>,
)
