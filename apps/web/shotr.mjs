import { chromium } from 'playwright'
const b = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox'] })
for (const [w,h,n] of [[1280,800,'r1280'],[1100,800,'r1100'],[390,844,'r390']]) {
  const p = await b.newPage({ viewport: { width: w, height: h } })
  await p.goto('http://127.0.0.1:5173/risk', { waitUntil: 'networkidle' }); await p.waitForTimeout(2500)
  const btn = p.locator('[data-testid^="risk-open-"]').first()
  if (await btn.count()) { await btn.click(); await p.waitForTimeout(2000) }
  const ov = await p.evaluate(() => document.documentElement.scrollWidth - innerWidth)
  console.log(n, 'overflowX', ov)
  await p.screenshot({ path: `/workspace/work/shots/${n}.png` })
}
await b.close()
