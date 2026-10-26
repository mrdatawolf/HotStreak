import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'

// Shared settings live in the repo-root .env (see .env.example).
const ROOT = fileURLToPath(new URL('..', import.meta.url))

export default defineConfig(({ mode }) => {
  // Only TRACKER_* keys, and only here in the dev server config; nothing is exposed to the browser bundle.
  const env = { ...loadEnv(mode, ROOT, 'TRACKER_'), ...process.env }
  const apiHost = env.TRACKER_API_HOST || '127.0.0.1'
  const apiPort = env.TRACKER_API_PORT || '8000'

  return {
    plugins: [react()],
    server: {
      // 0.0.0.0 lets other machines on the network open the app; the default keeps it local-only.
      host: env.TRACKER_WEB_IP || '127.0.0.1',
      port: Number(env.TRACKER_WEB_PORT || 5190),
      // IP addresses and localhost always work; hostnames (e.g. office-pc.local) must be listed.
      allowedHosts: (env.TRACKER_WEB_ALLOWED_HOSTS || '').split(',').map((h) => h.trim()).filter(Boolean),
      strictPort: true,
      // Forward API calls to FastAPI so the browser sees one origin.
      proxy: { '/api': `http://${apiHost}:${apiPort}` },
    },
  }
})
