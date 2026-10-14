import { useEffect, useState } from 'react'
import { supportApi, type DraftFinding } from '../../api/client'

/** 高严重度提示首次发送拦一次；同一草稿再次发送放行。 */
export function shouldHoldSend(findings: DraftFinding[], draft: string, acknowledgedDraft: string | null): boolean {
  return findings.some((item) => item.severity === 'high') && acknowledgedDraft !== draft
}

/** 输入停顿 500ms 后质检；切换会话或草稿变化时丢弃过期结果。 */
export function useDraftReview(conversationId: string | undefined, draft: string, enabled: boolean) {
  const [result, setResult] = useState<{ key: string; findings: DraftFinding[] }>({ key: '', findings: [] })
  const key = `${conversationId ?? ''}\u0000${draft}`
  useEffect(() => {
    if (!conversationId || !enabled || !draft.trim()) return
    let cancelled = false
    const timer = window.setTimeout(() => {
      supportApi.draftReview(conversationId, draft)
        .then((view) => { if (!cancelled) setResult({ key, findings: view.findings }) })
        .catch(() => undefined)
    }, 500)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [conversationId, draft, enabled, key])
  return result.key === key ? result.findings : []
}
