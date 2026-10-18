/**
 * Agent 模型分配（反馈 10-18 #4）失败方式：
 * M1 列表不显示各 Agent 与默认模型；M2 下拉不是网关真实模型；M3 保存没把选择/清空传给后端；M4 未改动时可误点保存。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ConfigProvider } from 'antd'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ agentModels: vi.fn(), saveAgentModels: vi.fn(), gatewayModels: vi.fn() }))
vi.mock('../../api/client', async (load) => ({ ...(await load<object>()), platformApi: api }))
import { AgentModelsPanel } from './AgentModelsPanel'

const agents = [
  { key: 'composer', label: '共情起草', description: '起草', tier: 'main', model: null, defaultModel: 'qwen-plus' },
  { key: 'verifier', label: '核验', description: '核验', tier: 'main', model: 'qwen-turbo', defaultModel: 'qwen-plus' },
]
beforeEach(() => {
  api.agentModels.mockResolvedValue({ agents })
  api.gatewayModels.mockResolvedValue({ models: ['qwen-plus', 'qwen-max', 'qwen-turbo'], configured: ['qwen-plus'], reachable: true })
  api.saveAgentModels.mockImplementation(async (a: Record<string, string | null>) => ({ agents: agents.map((x) => ({ ...x, model: a[x.key] })) }))
})

describe('AgentModelsPanel', () => {
  it('M1–M4', async () => {
    render(<ConfigProvider><AgentModelsPanel /></ConfigProvider>)
    expect(await screen.findByText('共情起草')).toBeInTheDocument()
    expect(screen.getByText('默认 · qwen-plus')).toBeInTheDocument()
    const save = screen.getByRole('button', { name: '保存分配' })
    expect(save).toBeDisabled()
    expect(api.gatewayModels).not.toHaveBeenCalled()
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '共情起草 模型' }))
    fireEvent.click(await screen.findByTitle('qwen-max'))
    expect(api.gatewayModels).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(save).not.toBeDisabled())
    fireEvent.click(save)
    await waitFor(() => expect(api.saveAgentModels).toHaveBeenCalledWith({ composer: 'qwen-max', verifier: 'qwen-turbo' }))
  })
})
