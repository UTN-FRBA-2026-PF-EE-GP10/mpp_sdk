import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vite'

// Build output stays in frontend/dist (gitignored) for now - this is a
// mock-data prototype, not yet the production build plan 023 will commit
// to scripts/curve_tracer_web/. Point outDir there only once this frontend
// is actually wired to a real backend and replaces the vanilla JS UI.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  base: './',
})
