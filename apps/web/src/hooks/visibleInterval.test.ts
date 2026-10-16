/**
 * 页面隐藏时暂停轮询（P2-2）。
 * V1 标签页在后台时仍每 1–1.5 秒请求，浪费接口与模型额度；
 * V2 回到前台后要等下一个周期才刷新，客服看到旧数据；
 * V3 卸载后计时器或监听器残留，切页后继续请求。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { visibleInterval } from './visibleInterval'

let state: DocumentVisibilityState = 'visible'
const setVisibility = (next: DocumentVisibilityState) => {
  state = next
  document.dispatchEvent(new Event('visibilitychange'))
}

beforeEach(() => {
  vi.useFakeTimers()
  state = 'visible'
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => state)
})
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

describe('visibleInterval', () => {
  it('隐藏时不调用，回到前台立即补一次', () => {
    const fn = vi.fn()
    const stop = visibleInterval(fn, 1000)
    vi.advanceTimersByTime(2000)
    expect(fn).toHaveBeenCalledTimes(2)
    setVisibility('hidden')
    vi.advanceTimersByTime(5000)
    expect(fn).toHaveBeenCalledTimes(2)
    setVisibility('visible')
    expect(fn).toHaveBeenCalledTimes(3)
    stop()
  })
  it('清理后不再调用', () => {
    const fn = vi.fn()
    const stop = visibleInterval(fn, 1000)
    stop()
    vi.advanceTimersByTime(3000)
    setVisibility('hidden')
    setVisibility('visible')
    expect(fn).not.toHaveBeenCalled()
  })
})
