import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Build directly into `desktop_shell/static` so FastAPI can keep serving a
 * plain static bundle while the source of truth moves into this workspace.
 */
export default defineConfig({
  base: "/static/",
  plugins: [react()],
  build: {
    outDir: "../../desktop_shell/static",
    emptyOutDir: true,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup-tests.ts",
  },
});
