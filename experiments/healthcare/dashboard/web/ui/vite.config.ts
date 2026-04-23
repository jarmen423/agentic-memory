import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * Production build writes into the FastAPI ``static/`` folder so a single
 * uvicorn process can serve API + UI on loopback for Cloudflare Tunnel.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8787",
    },
  },
  build: {
    outDir: "../server/static",
    emptyOutDir: true,
  },
});
