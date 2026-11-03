import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Local `npm run dev` → localhost; Compose sets VITE_API_PROXY_TARGET=http://api:8000.
const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET?.trim() || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
