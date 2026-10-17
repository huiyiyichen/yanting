/**
 * X-5 采用飞入输入框：建议正文的副本从卡片平滑移到客服回复输入框（300ms），
 * 随后输入框描边高亮 600ms。只是动效，不发送；不支持动画或减少动效时直接跳过。
 */
export const COMPOSER_SELECTOR = 'textarea[aria-label="客服回复输入框"]'

export async function flyToComposer(source: HTMLElement | null, text: string, doc: Document = document): Promise<void> {
  const target = doc.querySelector<HTMLElement>(COMPOSER_SELECTOR)
  const box = target?.closest<HTMLElement>('.ant-sender') ?? target
  const flash = () => {
    if (!box) return
    box.classList.add('yt-composer-flash')
    window.setTimeout(() => box.classList.remove('yt-composer-flash'), 600)
  }
  const reduced = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (!source || !target || reduced) { flash(); return }
  const from = source.getBoundingClientRect(), to = target.getBoundingClientRect()
  const ghost = doc.createElement('div')
  ghost.className = 'yt-fly-ghost'
  ghost.textContent = text
  Object.assign(ghost.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${from.width}px`, height: `${from.height}px` })
  doc.body.appendChild(ghost)
  try {
    if (typeof ghost.animate === 'function') {
      const dx = to.left - from.left, dy = to.top - from.top
      const sx = to.width / Math.max(1, from.width), sy = to.height / Math.max(1, from.height)
      await ghost.animate([
        { transform: 'translate(0, 0) scale(1)', opacity: 1 },
        { transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})`, opacity: 0.35 },
      ], { duration: 300, easing: 'cubic-bezier(.2,.7,.2,1)', fill: 'forwards' }).finished
    }
  } catch { /* 动画被打断不影响采用 */ }
  finally { ghost.remove() }
  flash()
}
