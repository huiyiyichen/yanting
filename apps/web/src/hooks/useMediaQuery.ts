/**
 * 响应式断点 Hook。
 *
 * 存在的理由：右侧辅助区与小屏会话列表必须按视口宽度改变形态
 * （抽屉 / 可收起），否则窄屏会出现无法操作的横向溢出 —— 已在 390x844
 * 的端到端用例中实测到 268px 溢出。
 */
import { useEffect, useState } from 'react'

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) {
      return false
    }
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) {
      return
    }
    const list = window.matchMedia(query)
    const handler = (event: MediaQueryListEvent) => setMatches(event.matches)
    setMatches(list.matches)
    list.addEventListener('change', handler)
    return () => list.removeEventListener('change', handler)
  }, [query])

  return matches
}

/** 视口是否窄于给定宽度。 */
export function useIsNarrow(maxWidth: number): boolean {
  return useMediaQuery(`(max-width: ${maxWidth}px)`)
}
