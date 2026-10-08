import { EditOutlined, PlusOutlined, ReloadOutlined, RocketOutlined, SaveOutlined, SearchOutlined, UploadOutlined } from '@ant-design/icons'
import { Alert, Button, Drawer, Empty, Form, Image, Input, Modal, Popconfirm, Segmented, Select, Space, Switch, Table, Tabs, Tag, message } from 'antd'
import { useCallback, useEffect, useRef, useState } from 'react'
import { knowledgeApi, platformApi, type KnowledgeEditRequest, type KnowledgeEditorView, type KnowledgeOverviewView, type KnowledgeProductView, type KnowledgeSearchView } from '../api/client'
import { QianniuTopbar } from '../components/QianniuTopbar'

const statuses: Record<string, string> = { draft: '待发布', published: '已发布', failed: '发布失败' }

export function KnowledgePage() {
  const [overview, setOverview] = useState<KnowledgeOverviewView | null>(null)
  const [rows, setRows] = useState<KnowledgeEditorView[]>([])
  const [products, setProducts] = useState<KnowledgeProductView[]>([])
  const [view, setView] = useState<string>('documents')
  const [base, setBase] = useState<string>('loreal-service')
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [publishing, setPublishing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState<KnowledgeEditorView | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [baseOpen, setBaseOpen] = useState(false)
  const [baseName, setBaseName] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchProduct, setSearchProduct] = useState<string>()
  const [searching, setSearching] = useState(false)
  const [searchResult, setSearchResult] = useState<KnowledgeSearchView | null>(null)
  const [form] = Form.useForm<KnowledgeEditRequest>()
  const scope = Form.useWatch(['metadata', 'scope'], form)
  const [toast, holder] = message.useMessage()
  const fileRef = useRef<HTMLInputElement>(null)
  const openRequest = useRef(0)
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [data, documents, catalogue] = await Promise.all([
        platformApi.knowledge(), knowledgeApi.documents(), knowledgeApi.products(),
      ])
      setOverview(data); setRows(documents); setProducts(catalogue); setError('')
    } catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  const edit = async (row?: KnowledgeEditorView) => {
    const request = ++openRequest.current
    setEditing(null); form.resetFields()
    if (row) {
      try {
        const detail = await knowledgeApi.document(row.documentId)
        if (request !== openRequest.current) return
        setEditing(detail); form.setFieldsValue(detail); setEditorOpen(true)
      } catch (err) { void toast.error((err as Error).message) }
    } else {
      form.setFieldsValue({
        knowledgeBaseId: base, title: '', content: '',
        metadata: { scope: 'general_consumer', provenance: 'user_supplied', sourceLabel: '', sourceUrl: '' },
      }); setEditorOpen(true)
    }
  }
  const save = async (values: KnowledgeEditRequest) => {
    setSaving(true)
    try {
      const body = { ...values, expectedRevision: editing?.revision ?? 0 }
      const result = editing ? await knowledgeApi.save(editing.documentId, body) : await knowledgeApi.create(body)
      setEditing(result); void toast.success('草稿已保存'); await load()
    } catch (err) { void toast.error((err as Error).message) }
    finally { setSaving(false) }
  }
  const publish = async () => {
    setPublishing(true)
    try {
      const result = await knowledgeApi.publish()
      if (result.ok) void toast.success(`已发布 · ${result.chunkCount} 个片段`)
      else setError(result.message)
      await load()
      if (!result.ok) setError(result.message)
    } catch (err) { setError((err as Error).message) }
    finally { setPublishing(false) }
  }
  const createBase = async () => {
    if (!baseName.trim()) return
    try {
      const result = await knowledgeApi.createBase(baseName)
      setBase(result.knowledgeBaseId); setBaseOpen(false); setBaseName(''); await load()
    } catch (err) { void toast.error((err as Error).message) }
  }
  const upload = async (file?: File) => {
    if (!file) return
    try {
      if (!/\.(md|markdown|txt)$/i.test(file.name) || file.size > 1_000_000) throw new Error('仅支持 1 MB 以内的 UTF-8 Markdown 或 TXT')
      const content = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
      await edit()
      form.setFieldsValue({ title: file.name.replace(/\.[^.]+$/, ''), content, knowledgeBaseId: base })
    } catch (err) { void toast.error((err as Error).message) }
    finally { if (fileRef.current) fileRef.current.value = '' }
  }
  const search = async () => {
    if (!searchQuery.trim()) return
    setSearching(true); setSearchResult(null)
    try { setSearchResult(await knowledgeApi.search(searchQuery, base, searchProduct)) }
    catch (err) { void toast.error((err as Error).message) }
    finally { setSearching(false) }
  }
  return <div className="desk-workbench">{holder}
    <QianniuTopbar title="知识库" stats={[
      { label: '文档', value: rows.length }, { label: '索引片段', value: overview?.chunkCount ?? 0 },
      { label: '待发布', value: rows.filter((r) => r.status !== 'published').length, warning: true },
    ]} actions={<Space wrap>
      <Button icon={<ReloadOutlined />} aria-label="刷新知识库" loading={loading} onClick={() => void load()} />
      <Button icon={<SearchOutlined />} onClick={() => setSearchOpen(true)}>检索测试</Button>
      <Popconfirm title="发布全部待发布文档？" onConfirm={() => void publish()} okText="发布" cancelText="取消">
        <Button type="primary" icon={<RocketOutlined />} loading={publishing}>发布索引</Button>
      </Popconfirm>
    </Space>} />
    <div className="knowledge-layout">
      <aside className="knowledge-bases">
        <div className="section-title-row"><strong>知识库</strong><Button type="text" icon={<PlusOutlined />} aria-label="新建知识库" onClick={() => setBaseOpen(true)} /></div>
        {overview?.knowledgeBases?.map((b) => <button className={`knowledge-base-item${base === b.knowledgeBaseId ? ' active' : ''}`} key={b.knowledgeBaseId} onClick={() => setBase(b.knowledgeBaseId)}>
          <span>{b.name}</span><Tag>{rows.filter((r) => r.knowledgeBaseId === b.knowledgeBaseId).length}</Tag>
        </button>)}
      </aside>
      <div className="desk-page-body">
        {error && <Alert type="error" title={error} showIcon />}
        <div className="desk-filterbar">
          <Segmented options={[{ value: 'documents', label: '文档' }, { value: 'products', label: '商品资料' }]} value={view} onChange={setView} />
          <Input prefix={<SearchOutlined />} placeholder="搜索文档" aria-label="搜索文档" value={query} allowClear onChange={(e) => setQuery(e.target.value)} />
          <Button icon={<UploadOutlined />} onClick={() => fileRef.current?.click()}>导入文档</Button>
          <Button icon={<PlusOutlined />} onClick={() => void edit()}>新建文档</Button>
          <input ref={fileRef} type="file" accept=".md,.markdown,.txt" hidden onChange={(e) => void upload(e.target.files?.[0])} />
        </div>
        {view === 'products' ? <Table<KnowledgeProductView> rowKey="sku" size="small" loading={loading}
          pagination={{ pageSize: 8 }} scroll={{ x: 700 }} dataSource={products.filter((p) =>
            `${p.name} ${p.sku}`.includes(query))} columns={[
            { title: '商品', render: (_, p) => <Space>{p.imageUrl ? <Image src={p.imageUrl} alt={p.name} width={48} height={64} style={{ objectFit: 'contain' }} /> : null}<span>{p.name}</span></Space> },
            { title: '标识', dataIndex: 'sku', width: 160 },
            { title: '来源', width: 100, render: (_, p) => <Tag>{p.identityKind === 'brand_reference' ? '品牌官网' : '赛题虚构'}</Tag> },
            { title: '地区', width: 80, render: (_, p) => p.market === 'US' ? '美国' : '中国大陆' },
            { title: '资料', width: 100, render: (_, p) => <Button size="small" aria-label={`查看资料 ${p.name}`} icon={<SearchOutlined />} onClick={() => {
              setView('documents'); setQuery(p.name); const matching = rows.find((r) => r.metadata?.productSku === p.sku)
              if (matching) { setBase(matching.knowledgeBaseId); setQuery(''); void edit(matching) }
              else { void edit().then(() => form.setFieldsValue({ title: p.name, metadata: {
                scope: 'product_specific', productSku: p.sku,
                provenance: p.identityKind === 'brand_reference' ? 'official_reference' : 'user_supplied',
                sourceLabel: p.identityKind === 'brand_reference' ? `${p.brand}官网商品资料` : '',
                sourceUrl: p.sourceUrl ?? '',
              } })) }
            }}>查看资料</Button> },
          ]} /> : <Table<KnowledgeEditorView> rowKey="documentId" size="small" loading={loading} pagination={{ pageSize: 12, showSizeChanger: false }} scroll={{ x: 790 }}
          dataSource={rows.filter((r) => r.knowledgeBaseId === base && r.title.includes(query))}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无文档" /> }}
          columns={[
            { title: '文档名称', dataIndex: 'title' },
            { title: '关联商品', width: 150, render: (_, r) => r.metadata?.productSku ?? '通用' },
            { title: '草稿版本', width: 90, render: (_, r) => r.revision ? `v${r.revision}` : '源版本' },
            { title: '发布状态', width: 115, render: (_, r) => <Tag color={r.status === 'published' ? 'success' : r.status === 'failed' ? 'error' : 'warning'}>{statuses[r.status] ?? r.status}</Tag> },
            { title: '检索启用', width: 100, render: (_, r) => <Switch size="small" aria-label={`启用 ${r.title}`} checked={r.enabled} disabled={!overview?.documents?.some((d) => d.documentId === r.documentId)}
              onChange={(enabled) => { void knowledgeApi.toggle(r.documentId, enabled).then(load).catch((err: Error) => toast.error(err.message)) }} /> },
            { title: '操作', width: 120, render: (_, r) => <Button size="small" icon={<EditOutlined />} onClick={() => void edit(r)}>编辑 / 片段</Button> },
          ]} />}
      </div>
    </div>
    <Drawer forceRender title={editing?.title ?? '新建文档'} size={760} open={editorOpen} onClose={() => { openRequest.current++; setEditorOpen(false) }}>
      {editing?.error && <Alert type="error" title={editing.error} showIcon />}
      <Tabs items={[
        { key: 'content', label: '文档内容', children: <Form form={form} layout="vertical" onFinish={(values) => void save(values)}>
          <div className="form-grid"><Form.Item name="title" label="标题" rules={[{ required: true, whitespace: true, message: '请填写标题' }]}><Input maxLength={300} /></Form.Item>
            <Form.Item name="knowledgeBaseId" label="所属知识库" rules={[{ required: true }]}><Select options={overview?.knowledgeBases?.map((b) => ({ value: b.knowledgeBaseId, label: b.name }))} /></Form.Item></div>
          <Form.Item name={['metadata', 'scope']} label="资料范围">
            <Segmented options={[
              { value: 'document_context', label: '普通文档' },
              { value: 'general_consumer', label: '通用资料' },
              { value: 'product_specific', label: '商品资料' },
            ]} onChange={() => form.setFieldValue(['metadata', 'productSku'], null)} />
          </Form.Item>
          {scope === 'product_specific' ? <Form.Item name={['metadata', 'productSku']} label="关联商品" rules={[{ required: true, message: '请选择商品' }]}>
            <Select showSearch optionFilterProp="label" options={products.map((p) => ({ value: p.sku, label: `${p.name} · ${p.sku}` }))} onChange={(sku) => {
              const product = products.find((p) => p.sku === sku)
              if (product?.identityKind === 'brand_reference') form.setFieldsValue({ metadata: {
                provenance: 'official_reference', sourceLabel: `${product.brand}官网商品资料`, sourceUrl: product.sourceUrl,
              } })
            }} />
          </Form.Item> : null}
          <div className="form-grid">
            <Form.Item name={['metadata', 'provenance']} label="来源性质"><Select options={[
              { value: 'user_supplied', label: '人工提供资料' },
              { value: 'official_reference', label: '官方公开参考' },
              { value: 'team_fictional', label: '团队虚构补充' },
            ]} /></Form.Item>
            <Form.Item name={['metadata', 'sourceLabel']} label="资料来源" rules={scope === 'product_specific' ? [{ required: true, whitespace: true, message: '请填写来源' }] : []}><Input maxLength={160} /></Form.Item>
          </div>
          <Form.Item name={['metadata', 'sourceUrl']} label="来源网址"><Input type="url" maxLength={2000} /></Form.Item>
          <Form.Item name="content" label="正文" rules={[{ required: true, whitespace: true, message: '请填写正文' }]}><Input.TextArea rows={18} maxLength={500000} /></Form.Item>
          <Button icon={<SaveOutlined />} type="primary" htmlType="submit" loading={saving}>保存草稿</Button>
        </Form> },
        { key: 'chunks', label: `已保存片段 ${editing?.chunks.length ?? 0}`, children: editing?.chunks.length ? editing.chunks.map((chunk, index) => <section className="service-section" key={index}>
          <div className="section-title-row"><Tag>{chunk.locator}</Tag><small>{chunk.charCount} 字</small></div><pre className="knowledge-text">{chunk.text}</pre>
        </section>) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无片段" /> },
      ]} />
    </Drawer>
    <Modal title="新建知识库" open={baseOpen} onCancel={() => setBaseOpen(false)} onOk={() => void createBase()} okText="创建" cancelText="取消" okButtonProps={{ disabled: !baseName.trim() }}>
      <Input aria-label="知识库名称" value={baseName} onChange={(e) => setBaseName(e.target.value)} placeholder="知识库名称" maxLength={100} />
    </Modal>
    <Drawer title="检索测试" size={620} open={searchOpen} onClose={() => setSearchOpen(false)}>
      <Select allowClear showSearch optionFilterProp="label" aria-label="检索关联商品" placeholder="全部商品" style={{ width: '100%', marginBottom: 12 }}
        options={products.map((p) => ({ value: p.sku, label: p.name }))} value={searchProduct} onChange={setSearchProduct} />
      <Input.Search aria-label="检索问题" placeholder="输入消费者问题" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onSearch={() => void search()} loading={searching} enterButton="检索" />
      {searchResult && <section className="service-section"><Tag>{searchResult.evidence.length} 条引用</Tag>
        {searchResult.evidence.map((e) => <blockquote className="evidence-quote" key={e.chunk_id}><strong>{e.document_title}</strong><p>{e.quoted_excerpt}</p><small>{e.source_locator}</small></blockquote>)}
        {!searchResult.evidence.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未命中" />}
      </section>}
    </Drawer>
  </div>
}
