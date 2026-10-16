import { MoonOutlined, SunOutlined } from '@ant-design/icons'
import { Button, Tooltip } from 'antd'
import { useTheme } from '../hooks/themeMode'

/** 顶栏明暗切换：点击在浅色与深色之间切换并记住选择。 */
export function ThemeToggle() {
  const { mode, cycle } = useTheme()
  const label = mode === 'dark' ? '切换到浅色' : '切换到深色'
  return <Tooltip title={label}><Button type="text" className="yt-theme-toggle" aria-label={label}
    icon={mode === 'dark' ? <SunOutlined /> : <MoonOutlined />} onClick={cycle} /></Tooltip>
}
