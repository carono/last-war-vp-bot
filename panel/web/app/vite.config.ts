import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// BUILT HERE, SERVED FROM THERE. The bundle lands in `panel/web/static/app/` and is
// committed with the change that produced it: the machine running the game has Python
// and no Node, so a front-end that had to be built on arrival would be a front-end
// nobody could install. `base` matches the folder it is served from, so every asset is
// asked for by an absolute path that survives a reload of a deep view.
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  build: {
    outDir: '../static/app',
    emptyOutDir: true,
    // One file each. A phone on a home network opens this over a slow link once and
    // then lives in it, and a hundred small chunks cost more round trips than they save.
    rollupOptions: { output: { manualChunks: undefined } },
  },
  server: {
    // `npm run dev` talks to a panel that is already running on this machine; the port
    // is the panel's own default and can be overridden by whoever is developing.
    proxy: { '/api': { target: process.env.PANEL_URL || 'http://127.0.0.1:9761' } },
  },
})
