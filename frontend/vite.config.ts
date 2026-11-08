import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Dedicated port for AgentForge so it never collides with other Vite
    // projects on the default 5173. strictPort fails loudly instead of
    // silently drifting to the next free port.
    port: 5180,
    strictPort: true,
    host: true
  }
})
