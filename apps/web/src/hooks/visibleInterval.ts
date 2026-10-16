/** 只在页面可见时轮询：隐藏时不发请求，回到前台立即补一次。返回清理函数。 */
export function visibleInterval(fn: () => void, ms: number): () => void {
  const tick = () => { if (document.visibilityState !== 'hidden') fn() }
  const onVisible = () => { if (document.visibilityState === 'visible') fn() }
  const timer = window.setInterval(tick, ms)
  document.addEventListener('visibilitychange', onVisible)
  return () => {
    window.clearInterval(timer)
    document.removeEventListener('visibilitychange', onVisible)
  }
}
