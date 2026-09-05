import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

// Build output is committed to scripts/curve_tracer_web/ on purpose: the Pi
// serves prebuilt static files from curve_tracer_server.py and must not
// need Node installed at runtime.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  base: './',
  build: {
    outDir: '../scripts/curve_tracer_web',
    emptyOutDir: true,
  },
  server: {
    // `pnpm dev` only serves the frontend - proxy API calls to a
    // separately-running `mpp-sdk curve-tracer-web` (default :8000) so
    // fetch('/api/...') works the same as it does from the built app.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
