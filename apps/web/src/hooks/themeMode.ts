import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'

/** 全局明暗（全景方案 1.4）：默认跟随系统，选择存本地；客户页始终浅色。 */
export type ThemeChoice = 'system' | 'light' | 'dark'
export const THEME_KEY = 'yt.theme'
const listeners = new Set<() => void>()

export function readChoice(): ThemeChoice {
  const value = typeof localStorage === 'undefined' ? null : localStorage.getItem(THEME_KEY)
  return value === 'light' || value === 'dark' ? value : 'system'
}

export function setChoice(choice: ThemeChoice) {
  if (choice === 'system') localStorage.removeItem(THEME_KEY)
  else localStorage.setItem(THEME_KEY, choice)
  listeners.forEach((fn) => fn())
}

const systemDark = () => typeof window !== 'undefined' && Boolean(window.matchMedia?.('(prefers-color-scheme: dark)').matches)

export function resolveTheme(choice: ThemeChoice, forceLight = false): 'light' | 'dark' {
  if (forceLight) return 'light'
  return choice === 'system' ? (systemDark() ? 'dark' : 'light') : choice
}

function subscribe(fn: () => void) {
  listeners.add(fn)
  const media = window.matchMedia?.('(prefers-color-scheme: dark)')
  media?.addEventListener?.('change', fn)
  window.addEventListener('storage', fn)
  return () => { listeners.delete(fn); media?.removeEventListener?.('change', fn); window.removeEventListener('storage', fn) }
}

/** 当前生效的明暗，并同步到 <html data-theme>。 */
export function useTheme(forceLight = false) {
  const choice = useSyncExternalStore(subscribe, readChoice, () => 'system' as ThemeChoice)
  const [, bump] = useState(0)
  useEffect(() => subscribe(() => bump((n) => n + 1)), [])
  const mode = resolveTheme(choice, forceLight)
  useEffect(() => { document.documentElement.dataset.theme = mode }, [mode])
  const cycle = useCallback(() => setChoice(choice === 'system' ? (mode === 'dark' ? 'light' : 'dark') : choice === 'dark' ? 'light' : 'dark'), [choice, mode])
  return { choice, mode, cycle }
}
