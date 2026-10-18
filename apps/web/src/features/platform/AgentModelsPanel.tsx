import { RobotOutlined } from '@ant-design/icons'
import { Button, message as antdMessage, Select, Skeleton } from 'antd'
import { useEffect, useMemo, useState } from 'react'
import { platformApi, type AgentModelItem } from '../../api/client'

/** 模型与成本 · Agent 模型分配（反馈 10-18 #4）：每个 LLM 型 Agent 可选网关模型，未配置用默认模型。 */
export function AgentModelsPanel() {
  const [message, holder] = antdMessage.useMessage()
  const [agents, setAgents] = useState<AgentModelItem[] | null>(null)
  const [draft, setDraft] = useState<Record<string, string | null>>({})
  const [gateway, setGateway] = useState<string[] | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Promise.resolve().then(() => platformApi.agentModels()).then((view) => {
      setAgents(view.agents)
      setDraft(Object.fromEntries(view.agents.map((a) => [a.key, a.model ?? null])))
    }).catch(() => setAgents([]))
  }, [])
  // 网关列表只在展开下拉时读取（页面加载不发远程请求）
  const loadGateway = (open: boolean) => {
    if (!open || gateway) return
    platformApi.gatewayModels().then((g) => setGateway([...new Set([...g.models, ...g.configured])])).catch(() => setGateway([]))
  }
  const dirty = useMemo(() => (agents ?? []).some((a) => (a.model ?? null) !== (draft[a.key] ?? null)), [agents, draft])
  const save = async () => {
    setSaving(true)
    try {
      const view = await platformApi.saveAgentModels(draft)
      setAgents(view.agents)
      setDraft(Object.fromEntries(view.agents.map((a) => [a.key, a.model ?? null])))
      void message.success('Agent 模型分配已保存，下一轮接待生效')
    } catch (err) {
      void message.error((err as Error).message || '保存失败')
    } finally { setSaving(false) }
  }

  return <section className="yt-agent-models" aria-label="Agent 模型分配">
    {holder}
    <div className="yt-am-head">
      <h2 className="yt-section-title">Agent 模型分配</h2>
      <span className="hint">未分配的 Agent 使用默认模型</span>
      <Button type="primary" size="small" disabled={!dirty} loading={saving} onClick={() => void save()}>保存分配</Button>
    </div>
    {!agents ? <Skeleton active paragraph={{ rows: 3 }} /> : <ul>
      {agents.map((a) => {
        const value = draft[a.key] ?? null
        const options = [...new Set([...(gateway ?? []), ...(value ? [value] : [])])].map((m) => ({ value: m, label: m }))
        return <li key={a.key}>
          <span className="ic"><RobotOutlined /></span>
          <span className="nm"><b>{a.label}</b><small>{a.description}</small></span>
          <Select size="small" allowClear showSearch aria-label={`${a.label} 模型`} className="sel"
            placeholder={`默认 · ${a.defaultModel ?? '未配置'}`} value={value ?? undefined}
            loading={gateway === null} onOpenChange={loadGateway} options={options}
            notFoundContent={gateway === null ? '读取网关模型…' : '网关没有返回模型'}
            onChange={(next) => setDraft((old) => ({ ...old, [a.key]: next ?? null }))} />
        </li>
      })}
    </ul>}
  </section>
}
