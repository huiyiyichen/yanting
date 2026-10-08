/**
 * Prompt 管理（可写）。
 *
 * 用户确认的范围变更（2026-09-25）：提示词要能新增/编辑/启停，而不是只能看。
 * 实现要点与边界：
 * 1. 模板存在 `prompt_template` 表里，`code` 是**用途标识**（Agent 按 code 取启用的那条）；
 * 2. **新模板默认停用**：改模型行为必须是一次显式动作，不能建完就生效；
 * 3. 编辑内容时 `revision` 自增，能回答「当时用的是哪一版」；
 * 4. 停用后 Agent **回退到代码常量**，不是空提示词——不会把链路打断；
 * 5. 内置模板来自代码常量：可以改、可以停，但不会被静默覆盖回默认值。
 */
import { EditOutlined, HistoryOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import {
  Alert,
  Button,
  Form,
  Drawer,
  Input,
  Modal,
  Popconfirm,
  Select,
  Switch,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useCallback, useEffect, useState } from 'react'

import { ApiError, platformApi, promptApi, type PromptTemplateView, type PromptRevisionView } from '../api/client'

const { Text } = Typography

interface TemplateForm {
  code: string
  name: string
  scenario: string
  content: string
}

export function PromptTemplatePage() {
  const [rows, setRows] = useState<PromptTemplateView[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [editing, setEditing] = useState<PromptTemplateView | null>(null)
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [history, setHistory] = useState<PromptTemplateView | null>(null)
  const [versions, setVersions] = useState<PromptRevisionView[]>([])
  const [form] = Form.useForm<TemplateForm>()
  const [messageApi, contextHolder] = message.useMessage()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await platformApi.templates())
      setError(null)
    } catch (err) {
      setError((err as ApiError).message)
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const openEditor = (row: PromptTemplateView) => {
    setEditing(row)
    form.setFieldsValue({
      code: row.code,
      name: row.name,
      scenario: row.scenario,
      content: row.content,
    })
  }

  const handleSave = useCallback(async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      if (editing) {
        await platformApi.updateTemplate(editing.templateId, {
          name: values.name,
          scenario: values.scenario,
          content: values.content,
          expectedRevision: editing.revision,
        })
        messageApi.success('已保存')
      } else {
        await platformApi.createTemplate(values)
        messageApi.success('已新增')
      }
      setEditing(null)
      setCreating(false)
      form.resetFields()
      await load()
    } catch (err) {
      messageApi.error(`保存失败：${(err as ApiError).message}`)
    } finally {
      setSaving(false)
    }
  }, [editing, form, load, messageApi])

  const handleStatus = useCallback(
    async (row: PromptTemplateView) => {
      setBusyId(row.templateId)
      try {
        const next = row.status === 'enabled' ? 'disabled' : 'enabled'
        await platformApi.setTemplateStatus(row.templateId, next)
        messageApi.success(next === 'enabled' ? '已启用' : '已停用')
        await load()
      } catch (err) {
        messageApi.error(`操作失败：${(err as ApiError).message}`)
      } finally {
        setBusyId(null)
      }
    },
    [load, messageApi],
  )

  const columns: ColumnsType<PromptTemplateView> = [
    {
      title: '模板',
      dataIndex: 'name',
      render: (name: string, row) => (
        <Space orientation="vertical" size={0}>
          <Text strong>{name}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {row.code}
            {row.isBuiltin ? ' · 内置' : ''}
          </Text>
        </Space>
      ),
    },
    { title: '适用场景', dataIndex: 'scenario', width: 220 },
    {
      title: '用途绑定', width: 180,
      render: (_: unknown, row) => <Select aria-label={`用途 ${row.name}`} placeholder="选择用途"
        value={row.boundPurposes?.[0]} style={{ width: 155 }}
        options={[{ value: 'LOREAL_AUTO_REPLY', label: '自动接待' }, { value: 'LOREAL_ASSISTANT', label: '人工接待辅助' }, { value: 'LOREAL_SAFETY', label: '安全补充' }]}
        onChange={(purpose) => { void promptApi.bind(row.templateId, purpose).then(load).catch((err: Error) => messageApi.error(err.message)) }} />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (status: string, row) => <Switch aria-label={`启用 ${row.name}`} checked={status === 'enabled'} loading={busyId === row.templateId} onChange={() => void handleStatus(row)} />,
    },
    {
      title: '版本',
      dataIndex: 'revision',
      width: 90,
      render: (revision: number) => <Tag>v{revision}</Tag>,
    },
    {
      title: '更新时间',
      dataIndex: 'updatedAt',
      width: 170,
      render: (value: string | undefined) => (
        <Text type="secondary">{(value ?? '').replace('T', ' ').slice(0, 19) || '—'}</Text>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 190,
      render: (_: unknown, row) => (
        <Space size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEditor(row)}>
            编辑
          </Button>
          <Button size="small" icon={<HistoryOutlined />} onClick={() => {
            setHistory(row); setVersions([])
            void promptApi.revisions(row.templateId).then(setVersions).catch((err: Error) => messageApi.error(err.message))
          }}>版本</Button>
        </Space>
      ),
    },
  ]

  return (
    <div className="anker-page">
      {contextHolder}
      <div className="anker-page-head">
        <div style={{ flex: 1, minWidth: 240 }}>
          <h1 className="anker-page-title">Prompt 管理</h1>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setCreating(true)
              setEditing(null)
              form.resetFields()
            }}
          >
            新建模板
          </Button>
        </Space>
      </div>

      {error ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          title="读取模板失败"
          description={error}
        />
      ) : null}


      <Table<PromptTemplateView>
        rowKey="templateId"
        size="small"
        loading={loading && rows.length === 0}
        columns={columns}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 1050 }}
        expandable={{
          expandedRowRender: (row) => (
            <pre
              className="anker-wrap"
              style={{
                margin: 0,
                maxHeight: 300,
                overflow: 'auto',
                fontSize: 12,
                lineHeight: 1.6,
                whiteSpace: 'pre-wrap',
              }}
            >
              {row.content}
            </pre>
          ),
        }}
      />

      <Modal
        open={creating || editing !== null}
        title={editing ? `编辑模板：${editing.code}` : '新建模板'}
        onCancel={() => {
          setCreating(false)
          setEditing(null)
        }}
        onOk={() => void handleSave()}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
        width={720}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="code"
            label="模板编码"
            rules={[{ required: true, message: '请填写编码' }]}
          >
            <Input disabled={Boolean(editing)} placeholder="CUSTOM_REPLY" maxLength={64} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请填写名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="scenario" label="适用场景">
            <Input />
          </Form.Item>
          <Form.Item
            name="content"
            label="提示词内容"
            rules={[{ required: true, message: '请填写内容' }]}
          >
            <Input.TextArea rows={12} />
          </Form.Item>
        </Form>
      </Modal>
      <Drawer title="版本记录" size={640} open={Boolean(history)} onClose={() => setHistory(null)}>
        {versions.map((version) => <section className="service-section" key={version.revision}>
          <div className="section-title-row"><strong>v{version.revision}</strong>
            <Popconfirm title="将此版本恢复为新版本？" okText="恢复" cancelText="取消" onConfirm={() => {
              if (!history) return
              void promptApi.restore(history.templateId, version.revision, history.revision).then(async (result) => {
                setHistory(result); setVersions(await promptApi.revisions(result.templateId)); await load()
              }).catch((err: Error) => messageApi.error(err.message))
            }}><Button size="small" disabled={history?.revision === version.revision}>恢复版本</Button></Popconfirm>
          </div><pre className="knowledge-text">{version.content}</pre>
        </section>)}
      </Drawer>
    </div>
  )
}

/** 兼容旧入口名：平台页里曾用 `PromptPage` 导出只读版本。 */
export const PromptPage = PromptTemplatePage
