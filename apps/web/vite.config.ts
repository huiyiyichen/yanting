import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发期通过 Vite 代理把 /api 转到本机后端，避免前端直接持有后端地址与凭证。
const API_TARGET = process.env.YANTING_API_TARGET ?? 'http://127.0.0.1:8000'
const apiProxy = {
  '/api': {
    target: API_TARGET,
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: apiProxy,
  },
  // 演示/验收用生产包预览：dev 模式每个模块单独一个请求（约 610 个，首次加载 3.8s），
  // 预览模式走单个打包文件，加载与切换明显更快。仍复用同一套 /api 代理。
  preview: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: apiProxy,
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
