import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // Relative paths, so the built site works from any folder (e.g. GitHub Pages /kaaran/)
  base: './',
  // The Python engine lives in ../tracer and is imported as text
  server: { fs: { allow: ['..'] } },
  worker: { format: 'es' },
})
