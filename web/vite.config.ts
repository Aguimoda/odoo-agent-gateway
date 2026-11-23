import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const gateway = process.env.GATEWAY_URL ?? "http://127.0.0.1:8000";

// The gateway serves the build at /app (ADR 0019). In development, Vite proxies the API to
// a running gateway so the session cookie stays same-origin.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../src/odoo_agent_gateway/web_dist", import.meta.url)),
    emptyOutDir: true,
    sourcemap: false,
    // No inline scripts or styles: the Content Security Policy allows neither.
    assetsInlineLimit: 0,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(
      ["/session", "/agent", "/approvals", "/admin", "/health"].map((path) => [
        path,
        { target: gateway, changeOrigin: false },
      ]),
    ),
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
