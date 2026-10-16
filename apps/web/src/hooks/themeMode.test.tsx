/**
 * 全局明暗（全景方案 1.4）失败方式：
 * T1 不跟随系统：未选择时系统为深色仍显示浅色。
 * T2 选择不持久：刷新后丢失。
 * T3 客户页跟着变深（客户页必须始终浅色）。
 * T4 深色令牌被后加载的 :root 覆盖（同优先级时后者胜），深色下出现白卡。
 */
import { act, render, screen, fireEvent } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ThemeToggle } from '../components/ThemeToggle'
import { THEME_KEY, readChoice, resolveTheme, useTheme } from './themeMode'

const media = (dark: boolean) => vi.spyOn(window, 'matchMedia').mockImplementation((query: string) => ({
  matches: dark && query.includes('dark'), media: query, onchange: null,
  addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
}) as unknown as MediaQueryList)

function Probe({ customer = false }: { customer?: boolean }) { const { mode } = useTheme(customer); return <span>{mode}</span> }

afterEach(() => { localStorage.removeItem(THEME_KEY); vi.restoreAllMocks() })

describe('themeMode', () => {
  it('T1 默认跟随系统', () => {
    media(true)
    expect(resolveTheme('system')).toBe('dark')
    render(<Probe />)
    expect(screen.getByText('dark')).toBeInTheDocument()
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
  it('T2 切换后写入本地并立即生效', () => {
    media(false)
    render(<><ThemeToggle /><Probe /></>)
    act(() => { fireEvent.click(screen.getByRole('button', { name: '切换到深色' })) })
    expect(localStorage.getItem(THEME_KEY)).toBe('dark')
    expect(readChoice()).toBe('dark')
    expect(screen.getByText('dark')).toBeInTheDocument()
  })
  it('T3 客户页始终浅色', () => {
    media(true)
    localStorage.setItem(THEME_KEY, 'dark')
    render(<Probe customer />)
    expect(screen.getByText('light')).toBeInTheDocument()
  })
  it('T4 深色令牌优先级高于 :root', () => {
    const css = readFileSync(resolve(__dirname, '../styles/yanting.css'), 'utf8')
    expect(css).toMatch(/html\[data-theme='dark'\] \{[^}]*--yt-card: #251b2e/)
    expect(css).not.toMatch(/(^|\n)\[data-theme='dark'\]/)
  })
})
