import { CheckCircleFilled, CheckOutlined, CloseOutlined, DownOutlined, EditOutlined, MinusCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { Button, Dropdown, Input, Segmented, Tooltip, message } from 'antd'
import { useState } from 'react'
import type { ConsumerServiceAssistantView } from '../../api/client'

type Suggestion = ConsumerServiceAssistantView['replySuggestions'][number]
type Instruction = 'gentler' | 'concise' | 'professional'

const STYLES: Record<string, string> = { recommended: '推荐', concise: '简洁', reassuring: '安抚' }
const REWRITES: { key: Instruction; label: string }[] = [
  { key: 'gentler', label: '更温和' }, { key: 'concise', label: '更简洁' }, { key: 'professional', label: '更专业' },
]

/** 回复建议卡：风格切换、编辑、改写、单风格重生成；核验通过前不可采用，采用只填草稿不发送。 */
export function ReplyCard({ suggestions, adoptable, automatic, generating, onAdopt, onIgnore, onRegenerate, onRewrite }: {
  suggestions: Suggestion[]
  adoptable: boolean
  automatic: boolean
  generating: boolean
  onAdopt: (style: string, body: string, edited: boolean) => void
  onIgnore: (style: string) => void
  onRegenerate: (style: string) => void
  onRewrite: (style: string, body: string, instruction: Instruction) => Promise<string>
}) {
  const [style, setStyle] = useState(suggestions[0]?.style ?? 'recommended')
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [editing, setEditing] = useState(false)
  const [rewriting, setRewriting] = useState(false)
  const [toast, holder] = message.useMessage()
  const current = suggestions.find((item) => item.style === style) ?? suggestions[0]
  if (!current) return null
  const original = current.body
  const body = edits[current.style] ?? original
  const edited = body !== original
  const blocked = !adoptable || automatic || generating
  const reason = automatic ? 'AI 接待中' : generating ? '生成中' : !adoptable ? '待核验' : undefined

  const rewrite = async (instruction: Instruction) => {
    setRewriting(true)
    try {
      const text = await onRewrite(current.style, body, instruction)
      setEdits((old) => ({ ...old, [current.style]: text }))
    } catch (err) { void toast.warning((err as Error).message) }
    finally { setRewriting(false) }
  }

  return <article className={`yt-reply${generating ? ' is-refreshing' : ''}`} aria-label="回复建议">
    {holder}
    <div className="yt-reply-head">
      {suggestions.length > 1 && <Segmented size="small" value={current.style}
        onChange={(value) => { setStyle(String(value)); setEditing(false) }}
        options={suggestions.map((item) => ({ value: item.style, label: STYLES[item.style] ?? item.style }))} />}
      <Tooltip title="重新生成此风格"><Button size="small" type="text" icon={<ReloadOutlined />}
        aria-label="重新生成此风格" disabled={generating} onClick={() => onRegenerate(current.style)} /></Tooltip>
    </div>
    {editing
      ? <Input.TextArea aria-label="编辑回复建议" autoSize={{ minRows: 3, maxRows: 8 }} maxLength={800} value={body}
        onChange={(event) => setEdits((old) => ({ ...old, [current.style]: event.target.value }))} />
      : <p className="yt-reply-body">{body}</p>}
    {(current.empathyDimensions?.length ?? 0) > 0 && <div className="yt-reply-empathy">
      {current.empathyDimensions!.map((item) =>
        <span key={item.key} title={item.reason} className={item.status === 'present' ? 'is-present' : 'is-missing'}>
          {item.status === 'present' ? <CheckCircleFilled /> : <MinusCircleOutlined />} {item.label}</span>)}
    </div>}
    <div className="yt-reply-actions">
      <Tooltip title={reason}><span>
        <Button type="primary" size="small" icon={<CheckOutlined />} disabled={blocked}
          onClick={() => onAdopt(current.style, body, edited)}>采用</Button>
      </span></Tooltip>
      <Button size="small" icon={<EditOutlined />} onClick={() => setEditing((value) => !value)}>{editing ? '完成' : '编辑'}</Button>
      <Dropdown disabled={generating || rewriting} trigger={['click']}
        menu={{ items: REWRITES.map((item) => ({ key: item.key, label: item.label })), onClick: ({ key }) => void rewrite(key as Instruction) }}>
        <Button size="small" loading={rewriting}>改写 <DownOutlined /></Button>
      </Dropdown>
      <Tooltip title="忽略"><Button size="small" type="text" icon={<CloseOutlined />} aria-label="忽略"
        onClick={() => onIgnore(current.style)} /></Tooltip>
    </div>
  </article>
}
