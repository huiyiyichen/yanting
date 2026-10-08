import { defineConfig, devices } from '@playwright/test'

/**
 * 端到端测试配置。
 *
 * 前端规范第 8 节要求验证 1440x900、1280x800 与至少一个小屏尺寸；
 * 这里把三种视口定义成 project，避免每次手工切换。
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  outputDir: 'test-results',
  use: {
    baseURL: process.env.ANKER_AGENT_WEB_BASE ?? 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // 使用本机已安装的 Chrome，避免依赖浏览器二进制下载
    // （本机 ms-playwright 缓存中没有与当前 Playwright 版本匹配的 chromium）。
    channel: 'chrome',
  },
  projects: [
    {
      name: 'desktop-1440x900',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      name: 'desktop-1280x800',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
    },
    {
      name: 'mobile-390x844',
      use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 } },
    },
  ],
})
