import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// 测试配置独立于 Vite 构建配置：Vitest 的 `test` 字段不属于 Vite 的 UserConfigExport，
// 混写会导致 `tsc -b` 报 "No overload matches this call"。
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
  },
})
