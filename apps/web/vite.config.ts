import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 开发期通过 Vite 代理把 /api 转到本机后端，避免前端直接持有后端地址与凭证。
const API_TARGET = process.env.ANKER_AGENT_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
