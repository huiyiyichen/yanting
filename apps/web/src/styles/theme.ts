/**
 * 视觉主题。
 *
 * 2026-10-14 改进方案（第 5 章，用户确认“根据改进方案继续完成开发”）：采用颜听深紫 + 香槟金主题，
 * 替代 2026-09-25 的“Ant Design 默认蓝”决定。香槟金只用于品牌与 AI 内容；
 * 绿 / 橙 / 红只表示情绪温度与风险等级；其余为中性色。设计令牌见 `yanting.css` 的 `--yt-*`。
 *
 * 想改品牌色时只改这里与 `yanting.css` 两处；组件里不要再写死颜色。
 */
import type { ThemeConfig } from 'antd'

/** 与 antd v6 默认色板一致的取值（用于 CSS 变量与文档引用）。 */
export const palette = {
  /** 颜听深紫（插件标题栏、主按钮、选中页签） */
  primary: '#3b2a4a',
  primaryHover: '#574066',
  primaryActive: '#2a1f33',
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
  success: '#22906f',
  warning: '#d98a0f',
  error: '#cc3550',
} as const

export const typography = {
  bodySize: 14,
  smallSize: 12,
  headingSize: 20,
} as const

/**
 * antd 主题：品牌主色、情绪语义色与中文字体栈。
 *
 * 为什么还留这个对象：`main.tsx` 需要 `ConfigProvider` 来统一语言与字体；
 * 阴影、间距等仍用 antd 默认值。
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
      '"Source Han Sans CN", "Source Han Sans SC", "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
    fontSize: typography.bodySize,
    colorLink: palette.primary,
    borderRadius: 8,
  },
}
