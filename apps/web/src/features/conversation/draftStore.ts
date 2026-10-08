/**
 * 草稿隔离（前端规范第 5.1 节、工程规范第 11 节）。
 *
 * 草稿以 `(conversationId, viewRole)` 为键隔离：切换会话不发送草稿、
 * 不中断其他会话的请求；切换视角分别保留客户草稿与客服草稿。
 */
import { useCallback, useState } from 'react'

export type DraftKey = string

export function draftKey(conversationId: string, viewRole: string): DraftKey {
  return `${conversationId}::${viewRole}`
}

export interface DraftStore {
  get: (conversationId: string, viewRole: string) => string
  set: (conversationId: string, viewRole: string, value: string) => void
  clear: (conversationId: string, viewRole: string) => void
  /** 读取全部草稿，便于测试断言隔离性。 */
  snapshot: () => Record<DraftKey, string>
}

export function useDraftStore(): DraftStore {
  const [drafts, setDrafts] = useState<Record<DraftKey, string>>({})

  const get = useCallback(
    (conversationId: string, viewRole: string) =>
      drafts[draftKey(conversationId, viewRole)] ?? '',
    [drafts],
  )

  const set = useCallback((conversationId: string, viewRole: string, value: string) => {
    setDrafts((previous) => ({ ...previous, [draftKey(conversationId, viewRole)]: value }))
  }, [])

  const clear = useCallback((conversationId: string, viewRole: string) => {
    setDrafts((previous) => {
      const next = { ...previous }
      delete next[draftKey(conversationId, viewRole)]
      return next
    })
  }, [])

  const snapshot = useCallback(() => ({ ...drafts }), [drafts])

  return { get, set, clear, snapshot }
}
