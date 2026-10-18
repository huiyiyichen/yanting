/**
 * 模型配置页（平台视角）。
 *
 * 用户反馈（2026-09-26）两条决定性的改动：
 * 1. **删掉顶部「运行时」卡片**——那是一条把「生效文本模型」单独拎出来的快捷入口，
 *    用户明确要求"切换模型在各自的界面"。现在模型选择就在对应能力的二级配置里，
 *    页面只保留能力表格 + 每行「配置 / 测试连接」。
 * 2. **向量与重排序不再写死"本地"**——两者都可以指向远端 OpenAI 兼容服务
 *    （服务地址 + 密钥 + 模型），本地 ONNX 只是向量的一种可选后端。
 *
 * 诚实边界（不要改成"看起来更顺"的写法）：
 * - 远端编码只有稠密向量（硅基流动 `/embeddings` 不返回稀疏词项），切过去后
 *   混合检索退化为单路稠密——界面上必须写明，不能假装还是双通道；
 * - 向量改动**需要重启**（编码后端在启动时构建，且索引与维度绑定），
 *   所以保存后的返回消息里会带这句提示，页面不谎报"已生效"；
 * - 重排序是纯 HTTP 调用，保存后立即生效；没配置时如实说"未启用"（不写"已重排序"）。
 */
import {
  ApiOutlined,
  ReloadOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Drawer,
  Form,
  Space,
  Table,
  Tag,
  Tabs,
  Tooltip,
  Typography,
  message,
} from 'antd'
import { useSearchParams } from 'react-router-dom'
import { TraceConsole } from '../features/trace/TraceConsole'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, platformApi, type ModelConfigView, type ModelProviderView, type UsageView } from '../api/client'
import { UsagePanel } from '../features/platform/UsagePanel'
import { ModelConfigForms, type ConfigForm } from '../features/platform/ModelConfigForms'
import { PageHeader } from '../components/PageHeader'

const { Text } = Typography

/** 能力状态 → 中文与颜色：`unavailable` 不等于错误，但必须一眼看出未就绪。 */
const STATE_META: Record<string, { label: string; color: string }> = {
  ready: { label: '已就绪', color: 'success' },
  degraded: { label: '降级', color: 'warning' },
  unavailable: { label: '不可用', color: 'default' },
  error: { label: '异常', color: 'error' },
}

export function ModelConfigPage() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'trace' ? 'trace' : 'models'
  const [config, setConfig] = useState<ModelConfigView | null>(null)
  const [usage, setUsage] = useState<UsageView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [testingRerank, setTestingRerank] = useState(false)
  const [editing, setEditing] = useState<ModelProviderView | null>(null)
  const [gateway, setGateway] = useState<{ models: string[]; configured: string[]; reachable: boolean } | null>(null)
  const [savingConfig, setSavingConfig] = useState(false)
  const [form] = Form.useForm<ConfigForm>()
  const [messageApi, contextHolder] = message.useMessage()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const loaded = await platformApi.models()
      setConfig(loaded)
      setUsage(await platformApi.usage().catch(() => null))
      setError(null)
    } catch (err) {
      setError((err as ApiError).message)
      setConfig(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  /** 打开某一行能力的二级配置：把该能力**当前真实值**填进表单。 */
  const openConfig = (row: ModelProviderView) => {
    setEditing(row)
    if (row.key === 'llm' || row.key === 'vision') {
      setGateway(null)
      platformApi.gatewayModels().then(setGateway).catch(() => setGateway({ models: [], configured: [], reachable: false }))
    }
    form.setFieldsValue({
      baseUrl: config?.baseUrl ?? '',
      // 密钥永远留空：接口只回掩码，回填掩码会被当成新密钥写进去
      apiKey: '',
      model: config?.textModel ?? '',
      visionModel: config?.visionModel ?? '',
      visionBaseUrl: config?.visionBaseUrl ?? '',
      visionApiKey: '',
      fastModel: config?.fastModel ?? '',
      embeddingBackend: config?.embeddingBackend ?? 'onnx-local',
      embeddingModel: config?.embeddingModel ?? '',
      embeddingPath: config?.embeddingPath ?? '',
      embeddingBaseUrl: config?.embeddingBaseUrl ?? '',
      embeddingApiKey: '',
      embeddingDimension: config?.embeddingDimension ?? null,
      rerankBackend: config?.rerankBackend ?? 'none',
      rerankBaseUrl: config?.rerankBaseUrl ?? '',
      rerankApiKey: '',
      rerankModel: config?.rerankModel ?? '',
    })
  }

  const handleSaveConfig = useCallback(async () => {
    if (!editing) {
      return
    }
    const values = await form.validateFields()
    setSavingConfig(true)
    try {
      // 只提交当前能力相关的字段：避免在「多模态」抽屉里误改 LLM 的地址
      const payload =
        editing.key === 'llm'
          ? { baseUrl: values.baseUrl, apiKey: values.apiKey, model: values.model, fastModel: values.fastModel }
          : editing.key === 'vision'
            ? { visionModel: values.visionModel, visionBaseUrl: values.visionBaseUrl, visionApiKey: values.visionApiKey }
            : editing.key === 'embedding'
              ? {
                  embeddingBackend: values.embeddingBackend,
                  embeddingModel: values.embeddingModel,
                  embeddingPath: values.embeddingPath,
                  embeddingBaseUrl: values.embeddingBaseUrl,
                  embeddingApiKey: values.embeddingApiKey,
                  embeddingDimension: values.embeddingDimension ?? undefined,
                }
              : editing.key === 'rerank'
                ? {
                    rerankBackend: values.rerankBackend,
                    rerankBaseUrl: values.rerankBaseUrl,
                    rerankApiKey: values.rerankApiKey,
                    rerankModel: values.rerankModel,
                  }
                : {}
      const result = await platformApi.saveConfig(payload)
      if (result.ok) {
        messageApi.success(result.message)
      } else {
        messageApi.warning(result.message)
      }
      setEditing(null)
      await load()
    } catch (err) {
      messageApi.error(`保存失败：${(err as ApiError).message}`)
    } finally {
      setSavingConfig(false)
    }
  }, [editing, form, load, messageApi])

  const handleTest = useCallback(
    async (model: string | null | undefined) => {
      if (!model) {
        return
      }
      setTesting(model)
      try {
        const result = await platformApi.testModel(model)
        if (result.ok) {
          messageApi.success(`${result.model} 连通（${result.latencySeconds}s）：${result.message}`)
        } else {
          // 失败必须显示真实原因，不能只弹一句「测试失败」
          messageApi.error(`${result.model} 不可用：${result.message}`)
        }
      } catch (err) {
        messageApi.error(`测试请求失败：${(err as ApiError).message}`)
      } finally {
        setTesting(null)
      }
    },
    [messageApi],
  )

  /** 重排序的"测试连接"要证明它真的在排序，因此回显两句样例的先后顺序。 */
  const handleTestRerank = useCallback(async () => {
    setTestingRerank(true)
    try {
      const result = await platformApi.testRerank()
      if (result.ok) {
        messageApi.success(`${result.model} 连通（${result.latencySeconds}s）：${result.message}`)
      } else {
        messageApi.error(`${result.model} 不可用：${result.message}`)
      }
    } catch (err) {
      messageApi.error(`测试请求失败：${(err as ApiError).message}`)
    } finally {
      setTestingRerank(false)
    }
  }, [messageApi])

  const currentTextModel = config?.textModel ?? null
  /**
   * 可切换的模型＝网关列表 ∪ 当前生效模型。
   *
   * 为什么必须带上当前生效模型：实测网关 `deepseek-chat` 可以正常调用，但
   * `/v1/models` 只返回 `deepseek-flash`/`deepseek-v4-pro`——只认列表会导致
   * 下拉框里没有当前模型，用户切走之后无法切回来。
   */
  const modelOptions = Array.from(
    new Set([...(gateway?.models ?? []), ...(config?.availableModels ?? []), currentTextModel].filter(Boolean) as string[]),
  )
  const embeddingOptions = Array.from(
    new Set(
      [...(config?.embeddingModelOptions ?? []), config?.embeddingModel].filter(
        Boolean,
      ) as string[],
    ),
  )
  const rerankOptions = Array.from(
    new Set([...(config?.rerankModelOptions ?? []), config?.rerankModel].filter(Boolean) as string[]),
  )

  const columns: ColumnsType<ModelProviderView> = [
    {
      title: '能力',
      dataIndex: 'label',
      width: 190,
      render: (label: string, row) => (
        <Space orientation="vertical" size={0}>
          <Text strong>{label}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {row.provider}
          </Text>
        </Space>
      ),
    },
    {
      title: '模型',
      dataIndex: 'model',
      width: 230,
      render: (model: string | null, row) =>
        model ? (
          <Space size={6}>
            <Text code>{model}</Text>
            {row.wired ? null : <Tag>未接入</Tag>}
          </Space>
        ) : (
          <Text type="secondary">未配置</Text>
        ),
    },
    {
      title: '状态',
      dataIndex: 'state',
      width: 100,
      render: (state: string) => {
        const meta = STATE_META[state] ?? { label: state, color: 'default' }
        return <Tag color={meta.color}>{meta.label}</Tag>
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      render: (_: unknown, row) => (
        <Space size={4}>
          {/* 每行打开对应能力的二级配置；只读能力也打开，但只说明边界（不做假表单） */}
          <Button size="small" icon={<SettingOutlined />} onClick={() => openConfig(row)}>
            配置
          </Button>
          {row.key === 'rerank' && row.wired ? (
            <Button
              size="small"
              icon={<ApiOutlined />}
              loading={testingRerank}
              onClick={() => void handleTestRerank()}
            >
              测试连接
            </Button>
          ) : row.wired && row.model ? (
            <Button
              size="small"
              icon={<ApiOutlined />}
              loading={testing === row.model}
              onClick={() => void handleTest(row.model)}
            >
              测试连接
            </Button>
          ) : (
            <Tooltip title="该能力尚未接入或未配置，没有可测试的连接">
              <Button size="small" disabled>
                测试连接
              </Button>
            </Tooltip>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div className="desk-workbench">
      {contextHolder}
      <PageHeader title="模型配置" actions={
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
          刷新
        </Button>
      } />
      <div className="yt-page">
      <Tabs className="yt-config-tabs" activeKey={tab} onChange={(key) => setParams((old) => { const next = new URLSearchParams(old); next.set('tab', key); if (key !== 'trace') next.delete('trace'); return next })}
        items={[{ key: 'models', label: '模型与成本', children: <>

      {error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          title="读取模型配置失败"
          description={<span className="yt-wrap">{error}</span>}
          action={
            <Button size="small" onClick={() => void load()}>
              重试
            </Button>
          }
        />
      ) : null}

      {config && (config.availableModels?.length ?? 0) === 0 && config.gatewayNote ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          title="网关未返回可用模型列表"
          description={config.gatewayNote}
        />
      ) : null}

      <Table<ModelProviderView>
        rowKey="key"
        size="small"
        loading={loading && !config}
        columns={columns}
        dataSource={config?.providers ?? []}
        pagination={false}
        locale={{ emptyText: error ? '配置读取失败' : '暂无数据' }}
      />

      <Drawer
        open={editing !== null}
        title={editing ? `配置：${editing.label}` : ''}
        size={560}
        onClose={() => setEditing(null)}
        extra={
          editing && ['llm', 'vision', 'embedding', 'rerank'].includes(editing.key) ? (
            <Button type="primary" loading={savingConfig} onClick={() => void handleSaveConfig()}>
              保存并测试
            </Button>
          ) : null
        }
      >
        <ModelConfigForms editing={editing} form={form} config={config} gateway={gateway} modelOptions={modelOptions}
          embeddingOptions={embeddingOptions} rerankOptions={rerankOptions} testingRerank={testingRerank}
          handleTestRerank={handleTestRerank} />
      </Drawer>
      {usage && <section className="yt-usage-section"><h2 className="yt-section-title">评测与成本</h2><UsagePanel usage={usage} /></section>}
        </> },
        { key: 'trace', label: 'Agent 追踪', children: <TraceConsole initialTrace={params.get('trace')} /> }]} />
      </div>
    </div>
  )
}
