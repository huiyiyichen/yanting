import { Button } from 'antd'
import { useState } from 'react'
import type { KnowledgeSearchView } from '../../api/client'

type Evidence = KnowledgeSearchView['evidence'][number]

/** 相关度 0–1：有精排分用精排分；否则融合分（RRF，只有相对意义）按本次最高分归一。 */
export function hitRelevance(evidence: Evidence, all: Evidence[]): number {
  if (evidence.rerank_score != null) return Math.max(0, Math.min(1, evidence.rerank_score))
  const top = Math.max(...all.map((item) => item.rrf_score))
  return top > 0 ? evidence.rrf_score / top : 0
}

export function KnowledgeHit({ evidence, relevance, fullText }: { evidence: Evidence; relevance: number; fullText?: string }) {
  const [open, setOpen] = useState(false)
  const percent = Math.round(relevance * 100)
  return <blockquote className="evidence-quote yt-khit">
    <div className="yt-khit-head"><strong>{evidence.document_title}</strong>
      <span className="yt-khit-rel" role="meter" aria-label="相关度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <i style={{ width: `${percent}%` }} /></span><b>{percent}</b></div>
    <p className={open ? 'is-full' : undefined}>{open && fullText ? fullText : evidence.quoted_excerpt}</p>
    <div className="yt-khit-foot"><small>{evidence.source_locator}</small>
      {fullText && <Button size="small" type="link" onClick={() => setOpen(!open)}>{open ? '收起' : '全文'}</Button>}</div>
  </blockquote>
}
