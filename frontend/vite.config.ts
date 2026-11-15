import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // GitHub Pages serves the site under /<repo>/; the workflow sets BASE_PATH. Locally it stays "/".
  base: process.env.BASE_PATH || "/",
  plugins: [react()],
})
