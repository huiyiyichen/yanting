import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfigProvider } from 'antd'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { KnowledgePage } from './PlatformPages'

afterEach(() => vi.unstubAllGlobals())

it('真实商品资料可打开来源和货号关联，读取不隐式发布', async () => {
  const metadata = {
    scope: 'product_specific', productSku: 'LRLWX26040', market: 'CN',
    productName: '黑胖子气垫 200 中性象牙白', provenance: 'official_reference',
    sourceLabel: '巴黎欧莱雅中国官网', sourceUrl: 'https://www.lorealparis.com.cn/product/example',
  }
  const document = {
    documentId: 'real-product', knowledgeBaseId: 'loreal-product-references',
    title: metadata.productName, content: '品牌公开说明，个人使用效果仍需核对。',
    revision: 1, status: 'draft', enabled: true, chunks: [], metadata,
  }
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.endsWith('/desk/operators')) return {
      ok: true, status: 200, text: async () => JSON.stringify({
        defaultOperatorId: 'G001', operators: [{ operatorId: 'G001', name: '模拟客服 G001' }],
      }),
    } as Response
    const payload = path.endsWith('/products') ? [{
      sku: 'LRLWX26040', name: metadata.productName, identityKind: 'brand_reference', market: 'CN',
    }] : path.endsWith('/documents/real-product') ? document
      : path.endsWith('/documents') ? [document]
        : { documents: [], chunkCount: 0, knowledgeBases: [{
          knowledgeBaseId: 'loreal-product-references', name: '欧莱雅公开商品资料',
        }] }
    return { ok: true, status: 200, text: async () => JSON.stringify(payload) } as Response
  })
  vi.stubGlobal('fetch', fetcher)
  const user = userEvent.setup()
  render(<ConfigProvider><MemoryRouter><KnowledgePage /></MemoryRouter></ConfigProvider>)
  await screen.findByText('欧莱雅公开商品资料')
  const productTab = screen.getByRole('radio', { name: '商品资料' }).closest('label')
  expect(productTab).not.toBeNull()
  await user.click(productTab!)
  expect(await screen.findByText('品牌官网')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: `查看资料 ${metadata.productName}` }))
  expect(await screen.findByLabelText('关联商品')).toBeInTheDocument()
  expect(screen.getByLabelText('资料来源')).toHaveValue('巴黎欧莱雅中国官网')
  expect(screen.getByLabelText('来源网址')).toHaveValue(metadata.sourceUrl)
  expect(fetcher.mock.calls.some(([path]) => String(path).endsWith('/publish'))).toBe(false)
}, 15000)
