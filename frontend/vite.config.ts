import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The FastAPI backend runs on :8000. In dev we proxy /api to it so the SPA can
// use same-origin relative URLs (no CORS juggling during development).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Tailwind v4 runs through its own Vite plugin above. Pin an empty PostCSS
  // config so Vite does not walk up the drive and pick a stray postcss.config.
  css: { postcss: { plugins: [] } },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
