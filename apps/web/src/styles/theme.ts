/**
 * 视觉主题。
 *
 * **2026-09-25 用户确认的变更**：主题统一改为 **Ant Design 默认设计语言**
 * （主色 `#1677ff`、官方组件外观与圆角），不再使用此前的薄荷 + 珊瑚定制皮肤。
 * 原话：「你可以将颜色和ant的同步，不需要按照原本的要求（如果改颜色就一起改，确保风格的统一）」。
 *
 * 因此本文件只保留三类内容：
 * 1. **默认令牌的显式声明**（写出来是为了让「我们确实用 antd 默认值」可核对，
 *    而不是散落在各组件里被覆盖）；
 * 2. 少量**业务语义色**（成功/警告/危险沿用 antd 语义色，不自定义品牌色）；
 * 3. 组件级别的极小偏差（目前没有）。
 *
 * 想改品牌色时只改这里一处；组件里不要再写死颜色（`global.css` 里的
 * `--anker-*` 变量已同步为 antd 默认色板的取值）。
 */
import type { ThemeConfig } from 'antd'

/** 与 antd v6 默认色板一致的取值（用于 CSS 变量与文档引用）。 */
export const palette = {
  /** antd 默认主色 */
  primary: '#1677ff',
  primaryHover: '#4096ff',
  primaryActive: '#0958d9',
  /** 默认文本与边框 */
  text: 'rgba(0, 0, 0, 0.88)',
  textSecondary: 'rgba(0, 0, 0, 0.65)',
  textTertiary: 'rgba(0, 0, 0, 0.45)',
  border: '#d9d9d9',
  borderSecondary: '#f0f0f0',
  /** 布局底色（antd Layout 默认） */
  layoutBg: '#f5f5f5',
  container: '#ffffff',
  /** 语义色 */
  success: '#52c41a',
  warning: '#faad14',
  error: '#ff4d4f',
} as const

export const typography = {
  bodySize: 14,
  smallSize: 12,
  headingSize: 20,
} as const

/**
 * antd 主题：**不使用任何定制色**，只声明默认值与中文字体栈。
 *
 * 为什么还留这个对象：`main.tsx` 需要 `ConfigProvider` 来统一语言与字体；
 * 颜色、圆角、阴影全部交给 antd 默认值，组件外观因此与官方文档一致。
 */
export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: palette.primary,
    colorInfo: palette.primary,
    colorSuccess: palette.success,
    colorWarning: palette.warning,
    colorError: palette.error,
    colorBgLayout: palette.layoutBg,
    colorBgContainer: palette.container,
    fontFamily:
      '"Inter", "PingFang SC", "HarmonyOS Sans SC", "Microsoft YaHei", "Hiragino Sans GB", system-ui, sans-serif',
    fontSize: typography.bodySize,
    // 圆角、行高、阴影、间距等一律用 antd 默认值：不写就是默认，
    // 写了反而会在升级时与官方外观产生偏差。
  },
}
