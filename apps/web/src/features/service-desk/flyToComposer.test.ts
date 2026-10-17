/**
 * X-5 采用飞入输入框。失败方式：
 * F1 飞入副本留在页面上（未移除），挡住输入框。
 * F2 输入框没有高亮，或高亮不消失。
 * F3 找不到输入框 / 不支持动画时抛错，导致“采用”失效。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { COMPOSER_SELECTOR, flyToComposer } from './flyToComposer'

afterEach(() => { document.body.innerHTML = ''; vi.useRealTimers() })

describe('flyToComposer', () => {
  it('F1/F2 副本动画后移除，输入框高亮 600ms', async () => {
    vi.useFakeTimers()
    document.body.innerHTML = '<div class="ant-sender"><textarea aria-label="客服回复输入框"></textarea></div><p id="s">亲</p>'
    const source = document.getElementById('s')!
    const animate = vi.fn(() => ({ finished: Promise.resolve() }))
    ;(HTMLElement.prototype as unknown as { animate: unknown }).animate = animate
    await flyToComposer(source, '亲')
    expect(animate).toHaveBeenCalledWith(expect.any(Array), expect.objectContaining({ duration: 300 }))
    expect(document.querySelector('.yt-fly-ghost')).toBeNull()
    const box = document.querySelector(COMPOSER_SELECTOR)!.closest('.ant-sender')!
    expect(box).toHaveClass('yt-composer-flash')
    vi.advanceTimersByTime(600)
    expect(box).not.toHaveClass('yt-composer-flash')
    delete (HTMLElement.prototype as unknown as { animate?: unknown }).animate
  })
  it('F3 没有输入框时安静返回', async () => {
    await expect(flyToComposer(null, 'x')).resolves.toBeUndefined()
  })
})
