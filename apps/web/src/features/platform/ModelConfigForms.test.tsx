/**
 * P2-2 模型配置拆分。失败方式：
 * M1 拆出后抽屉按能力切换表单失效（文本模型没有接口地址/模型字段）。
 * M2 重排序“未启用”时仍渲染远端地址字段。
 */
import { render, screen } from '@testing-library/react'
import { ConfigProvider, Form } from 'antd'
import { describe, expect, it, vi } from 'vitest'
import type { ModelProviderView } from '../../api/client'
import { ModelConfigForms, type ConfigForm } from './ModelConfigForms'

function Harness({ editing, values }: { editing: Partial<ModelProviderView>; values?: Partial<ConfigForm> }) {
  const [form] = Form.useForm<ConfigForm>()
  return <ConfigProvider><Form form={form} initialValues={values} component={false}>
    <ModelConfigForms editing={editing as ModelProviderView} form={form} config={null} gateway={{ models: ['deepseek-flash', 'deepseek-v4-pro'], configured: ['deepseek-chat'], reachable: true }} modelOptions={['m1']}
      embeddingOptions={[]} rerankOptions={[]} testingRerank={false} handleTestRerank={vi.fn()} /></Form></ConfigProvider>
}

describe('ModelConfigForms', () => {
  /** 用户反馈 10-18 #6：网关可用模型来自网关真实列表；配置了但不在列表里的要标出来。 */
  it('M3 网关列表与不在列表的配置', () => {
    render(<Harness editing={{ key: 'llm', label: '文本模型' }} />)
    expect(screen.getByText('deepseek-v4-pro')).toBeInTheDocument()
    expect(screen.getByText('deepseek-chat · 不在列表')).toBeInTheDocument()
  })
  it('M1 文本模型表单有接口地址与模型', () => {
    render(<Harness editing={{ key: 'llm', label: '文本模型' }} />)
    expect(screen.getByLabelText('接口地址（Base URL）')).toBeInTheDocument()
  })
  it('M2 重排序未启用时不显示远端地址', () => {
    render(<Harness editing={{ key: 'rerank', label: '重排序' }} values={{ rerankBackend: 'none' }} />)
    expect(screen.queryByLabelText(/重排序.*地址|Base URL/)).toBeNull()
  })
})
