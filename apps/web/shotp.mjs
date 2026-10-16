import { chromium } from 'playwright'
const b = await chromium.launch({ executablePath: '/usr/bin/chromium', args: ['--no-sandbox'] })
for (const w of [1440, 1280, 390]) {
  const p = await b.newPage({ viewport: { width: w, height: 900 } })
  await p.goto('http://127.0.0.1:5173/support?view=panorama', { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  const tiles = p.locator('.yt-ptile')
  if (await tiles.count()) { await p.locator('.yt-plane.is-wait .yt-ptile').first().click().catch(() => tiles.first().click()); await p.waitForTimeout(1200) }
  const ox = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  console.log(w, 'overflowX', ox)
  await p.screenshot({ path: `/workspace/work/shots/pano-${w}.png`, fullPage: w === 390 })
}
await b.close()
