/** 模型配置抽屉里的各能力表单（文本 / 视觉 / 向量 / 重排序 / 只读说明），从 ModelConfigPage 拆出（P2-2）。 */
import { ApiOutlined, CheckCircleTwoTone, CloseCircleTwoTone } from '@ant-design/icons'
import { Alert, Button, Form, Input, InputNumber, Select, Space, Tag, Tooltip, Typography, type FormInstance } from 'antd'

import type { ModelConfigView, ModelProviderView } from '../../api/client'

const { Text } = Typography

export interface ConfigForm {
  baseUrl: string
  apiKey: string
  model: string
  visionModel: string
  visionBaseUrl: string
  visionApiKey: string
  fastModel: string
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
export function ModelSelect({
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

export function ModelConfigForms({ editing, form, config, gateway, modelOptions, embeddingOptions, rerankOptions, testingRerank, handleTestRerank }: {
  editing: ModelProviderView | null
  form: FormInstance<ConfigForm>
  config: ModelConfigView | null
  /** null=正在向网关取列表 */
  gateway: { models: string[]; configured: string[]; reachable: boolean } | null
  modelOptions: string[]
  embeddingOptions: string[]
  rerankOptions: string[]
  testingRerank: boolean
  handleTestRerank: () => Promise<void> | void
}) {
  return <>
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
          label={`API Key（当前 ${config?.apiKeyMasked || '未配置'}）`}
        >
          <Input.Password placeholder="留空＝不修改" autoComplete="new-password" />
        </Form.Item>
        <Form.Item
          name="model"
          label="文本模型"
        >
          <ModelSelect options={modelOptions} placeholder="选择或输入模型名" />
        </Form.Item>
        <Form.Item name="fastModel" label="快速模型"><ModelSelect options={modelOptions} /></Form.Item>
        {/* 网关可用模型放在这里才有用：选模型的人就在这个抽屉里 */}
        <Form.Item label="网关可用模型">
          {gateway == null ? <Text type="secondary">正在读取网关…</Text> : gateway.reachable ? (
            <Space size={6} wrap>
              {gateway.models.map((item) => (
                <Tag key={item} icon={<CheckCircleTwoTone twoToneColor="#52c41a" />}>{item}</Tag>
              ))}
              {gateway.configured.filter((m) => !gateway.models.includes(m)).map((item) => (
                <Tooltip key={item} title="当前配置的模型不在网关列表里，网关可能把它当作别名转到其他模型">
                  <Tag color="warning">{item} · 不在列表</Tag></Tooltip>
              ))}
            </Space>
          ) : (
            <Text type="secondary">
              <CloseCircleTwoTone twoToneColor="#bfbfbf" /> 网关未返回模型列表，请检查地址与密钥
            </Text>
          )}
        </Form.Item>
      </Form>
    ) : null}

    {editing?.key === 'vision' ? (
      <Form form={form} layout="vertical">
        <Form.Item name="visionBaseUrl" label="视觉服务地址"><Input placeholder="留空复用文本服务" /></Form.Item>
        <Form.Item name="visionApiKey" label={`视觉 API Key（${config?.visionApiKeyMasked || '复用文本服务'}）`}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
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

  </>
}
