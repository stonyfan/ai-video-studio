import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 部署在 /admin/ 路径下，所以 base 必须是 /admin/
// dev 模式 proxy /api → backend（避免 CORS）
export default defineConfig({
  plugins: [react()],
  base: '/admin/',
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
  },
})
