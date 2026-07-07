import { resolve } from 'path'
import { defineConfig } from 'electron-vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  main: {
    build: {
      outDir: 'out/main',
      lib: {
        entry: resolve(__dirname, 'electron/main.ts')
      },
      rollupOptions: {
        external: ['electron', 'chokidar', 'electron-updater']
      }
    }
  },
  preload: {
    build: {
      outDir: 'out/preload',
      lib: {
        entry: resolve(__dirname, 'electron/preload.ts')
      }
    }
  },
  renderer: {
    root: 'src',
    build: {
      outDir: 'out/renderer',
      rollupOptions: {
        input: resolve(__dirname, 'src/index.html')
      }
    },
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src')
      }
    },
    plugins: [react()]
  }
})
