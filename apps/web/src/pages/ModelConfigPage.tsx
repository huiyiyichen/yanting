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
  CheckCircleTwoTone,
  CloseCircleTwoTone,
  ReloadOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, platformApi, type ModelConfigView, type ModelProviderView } from '../api/client'

const { Text } = Typography

/** 能力状态 → 中文与颜色：`unavailable` 不等于错误，但必须一眼看出未就绪。 */
const STATE_META: Record<string, { label: string; color: string }> = {
  ready: { label: '已就绪', color: 'success' },
  degraded: { label: '降级', color: 'warning' },
  unavailable: { label: '不可用', color: 'default' },
  error: { label: '异常', color: 'error' },
}

interface ConfigForm {
  baseUrl: string
  apiKey: string
  model: string
  visionModel: string
  embeddingBackend: string
  embeddingModel: string
  embeddingPath: string
  embeddingBaseUrl: string
  embeddingApiKey: string
  embeddingDimension: number | null
  rerankBackend: string
  rerankBaseUrl: string
  rerankApiKey: string
  rerankModel: string
}

/**
 * 可选可填的模型选择框。
 *
 * 为什么需要包装：antd 的 `Select mode="tags"` 值必须是**数组**，而表单字段是
 * 字符串；直接把 `mode="tags"` 放进 `Form.Item` 会由 Form 注入字符串 value，
 * 运行时抛 `value should be array when mode is multiple or tags`（走查脚本实测抓到）。
 * 这里做一次数组↔字符串转换，表单侧仍然只存字符串。
 */
function ModelSelect({
  value,
  onChange,
  options,
  placeholder,
}: {
  value?: string
  onChange?: (value: string) => void
  options: string[]
  placeholder?: string
}) {
  return (
    <Select
      showSearch
      mode="tags"
      maxCount={1}
      placeholder={placeholder}
      value={value ? [value] : []}
      options={options.map((item) => ({ value: item, label: item }))}
      onChange={(next: string[]) => onChange?.(next[0] ?? '')}
    />
  )
}

export function ModelConfigPage() {
  const [config, setConfig] = useState<ModelConfigView | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [testingRerank, setTestingRerank] = useState(false)
  const [editing, setEditing] = useState<ModelProviderView | null>(null)
  const [savingConfig, setSavingConfig] = useState(false)
  const [form] = Form.useForm<ConfigForm>()
  const [messageApi, contextHolder] = message.useMessage()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const loaded = await platformApi.models()
      setConfig(loaded)
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
    form.setFieldsValue({
      baseUrl: config?.baseUrl ?? '',
      // 密钥永远留空：接口只回掩码，回填掩码会被当成新密钥写进去
      apiKey: '',
      model: config?.textModel ?? '',
      visionModel: config?.visionModel ?? '',
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
          ? { baseUrl: values.baseUrl, apiKey: values.apiKey, model: values.model }
          : editing.key === 'vision'
            ? { visionModel: values.visionModel }
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
    new Set([...(config?.availableModels ?? []), currentTextModel].filter(Boolean) as string[]),
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
    <div className="anker-page">
      {contextHolder}
      <div className="anker-page-head">
        <div style={{ flex: 1, minWidth: 240 }}>
          <h1 className="anker-page-title">模型配置</h1>
        </div>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
          刷新
        </Button>
      </div>

      {error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          title="读取模型配置失败"
          description={<span className="anker-wrap">{error}</span>}
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
        {editing?.key === 'llm' ? (
          <Form form={form} layout="vertical">
            <Form.Item
              name="baseUrl"
              label="接口地址（Base URL）"
              rules={[{ required: true, message: '请填写接口地址' }]}
            >
              <Input placeholder="https://api.deepseek.com" />
            </Form.Item>
            <Form.Item
              name="apiKey"
              label={`API Key（当前 ${config?.apiKeyMasked ?? '未配置'}）`}
            >
              <Input.Password placeholder="留空＝不修改" autoComplete="new-password" />
            </Form.Item>
            <Form.Item
              name="model"
              label="文本模型"
            >
              <ModelSelect options={modelOptions} placeholder="选择或输入模型名" />
            </Form.Item>
            {/* 网关可用模型放在这里才有用：选模型的人就在这个抽屉里 */}
            <Form.Item label="网关可用模型">
              {(config?.availableModels?.length ?? 0) > 0 ? (
                <Space size={6} wrap>
                  {(config?.availableModels ?? []).map((item) => (
                    <Tag key={item} icon={<CheckCircleTwoTone twoToneColor="#52c41a" />}>
                      {item}
                    </Tag>
                  ))}
                </Space>
              ) : (
                <Text type="secondary">
                  <CloseCircleTwoTone twoToneColor="#bfbfbf" />{' '}
                  {config?.gatewayNote ?? '网关未返回模型列表'}
                </Text>
              )}
            </Form.Item>
          </Form>
        ) : null}

        {editing?.key === 'vision' ? (
          <Form form={form} layout="vertical">
            <Form.Item
              name="visionModel"
              label="多模态模型"
            >
              <ModelSelect options={modelOptions} placeholder="选择或输入模型名" />
            </Form.Item>
          </Form>
        ) : null}

        {editing?.key === 'embedding' ? (
          <Form form={form} layout="vertical">
            <Form.Item
              name="embeddingBackend"
              label="编码后端"
            >
              <Select
                options={[
                  { value: 'onnx-local', label: '本地 ONNX（稠密 + 稀疏）' },
                  { value: 'http', label: '远端 API（OpenAI 兼容 /embeddings，仅稠密）' },
                ]}
              />
            </Form.Item>
            <Form.Item
              name="embeddingModel"
              label="向量模型 ID"
              rules={[{ required: true, message: '请填写向量模型 ID' }]}
            >
              <ModelSelect options={embeddingOptions} placeholder="BAAI/bge-m3" />
            </Form.Item>
            <Form.Item
              noStyle
              shouldUpdate={(prev, next) => prev.embeddingBackend !== next.embeddingBackend}
            >
              {({ getFieldValue }) =>
                getFieldValue('embeddingBackend') === 'http' ? (
                  <>
                    <Form.Item
                      name="embeddingBaseUrl"
                      label="服务地址"
                    >
                      <Input placeholder="https://api.siliconflow.cn/v1" />
                    </Form.Item>
                    <Form.Item
                      name="embeddingApiKey"
                      label={`API Key（当前 ${config?.embeddingApiKeyMasked || '未配置'}）`}
                    >
                      <Input.Password placeholder="留空＝不修改" autoComplete="new-password" />
                    </Form.Item>
                    <Form.Item
                      name="embeddingDimension"
                      label="向量维度（可选）"
                    >
                      <InputNumber min={64} max={8192} style={{ width: '100%' }} />
                    </Form.Item>
                  </>
                ) : (
                  <Form.Item
                    name="embeddingPath"
                    label="本地模型路径"
                  >
                    <Input placeholder="留空＝默认路径" />
                  </Form.Item>
                )
              }
            </Form.Item>
            <Alert
              type="warning"
              showIcon
              title="更换模型需重启并重建索引"
            />
          </Form>
        ) : null}

        {editing?.key === 'rerank' ? (
          <Form form={form} layout="vertical">
            <Form.Item name="rerankBackend" label="是否启用精排">
              <Select
                options={[
                  { value: 'http', label: '启用（远端 OpenAI 兼容 /rerank）' },
                  { value: 'none', label: '不启用（按召回顺序返回）' },
                ]}
              />
            </Form.Item>
            <Form.Item name="rerankBaseUrl" label="服务地址">
              <Input placeholder="https://api.siliconflow.cn/v1" />
            </Form.Item>
            <Form.Item
              name="rerankApiKey"
              label={`API Key（当前 ${config?.rerankApiKeyMasked || '未配置'}）`}
            >
              <Input.Password placeholder="留空＝不修改" autoComplete="new-password" />
            </Form.Item>
            <Form.Item name="rerankModel" label="重排序模型">
              <ModelSelect options={rerankOptions} placeholder="BAAI/bge-reranker-v2-m3" />
            </Form.Item>
            <Space size={8}>
              <Button
                icon={<ApiOutlined />}
                loading={testingRerank}
                onClick={() => void handleTestRerank()}
              >
                测试连接
              </Button>
            </Space>
          </Form>
        ) : null}

        {editing?.key === 'knowledge_index' ? (
          <Space orientation="vertical" size={12} style={{ width: '100%' }}>
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="存储">Qdrant 本地目录（向量 + payload）</Descriptions.Item>
              <Descriptions.Item label="元数据">库里的 knowledge_snapshot / document / chunk 表</Descriptions.Item>
              <Descriptions.Item label="重建命令">
                python scripts/ingest_knowledge.py
              </Descriptions.Item>
              <Descriptions.Item label="隔离环境注意">
                两处都要准备（只复制 Qdrant 目录会导致检索恒为 not_found，见缺陷第 39 项）
              </Descriptions.Item>
            </Descriptions>
          </Space>
        ) : null}
      </Drawer>
    </div>
  )
}
