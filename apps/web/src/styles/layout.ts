/**
 * 工作台响应式布局常量。
 *
 * 依据前端规范第 4 节：
 * - 客服：左栏 + 约 248px 会话队列 + 弹性聊天区 + 约 330px 右侧辅助区；
 * - 较窄桌面将右侧面板改为客服专属可开合抽屉；移动端会话列表可收起。
 *
 * 这些宽度也用于 CSS 媒体查询断点与浮层定位，避免两处各写一份魔法数字。
 */
export const SUPPORT_LAYOUT = {
  /** 会话队列宽度 */
  queueWidth: 248,
  /** 右侧辅助区宽度 */
  sidebarWidth: 330,
  /** 低于此宽度时右侧改为抽屉 */
  sidebarDrawerBreakpoint: 1100,
  /** 低于此宽度时会话队列可收起 */
  queueCollapseBreakpoint: 820,
} as const

export const CUSTOMER_LAYOUT = {
  listWidth: 248,
  /** 低于此宽度时会话列表可收起 */
  listCollapseBreakpoint: 820,
} as const

/**
 * 导航栏与浮层的定位参考。
 *
 * 外壳是「浅薄荷底 + 三块白色圆角面板 + 10px 缝隙」（`global.css` 的
 * `.anker-shell`／`--anker-gap`），所以浮层的左/上起点要把外壳内边距与缝隙算进去，
 * 否则会盖住运行状态横幅或压住左侧导航栏。
 */
export const OVERLAY_LAYOUT = {
  /** 浮层顶部起点：顶部状态横幅已移除，只剩外壳内边距 10 */
  bannerHeight: 10,
  /** 浮层左侧起点：外壳内边距 10 + 窄屏图标栏 72 + 缝隙 10 */
  navRailWidth: 92,
  /** 会话队列 / 列表宽度 */
  panelWidth: 248,
} as const
