import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  root: path.resolve(rootDir, "src/client"),
  publicDir: path.resolve(rootDir, "public"),
  server: {
    port: 5173,
    /** Firefox résout souvent `localhost` en IPv6 (::1) ; sans ça, Vite peut n’écouter que sur 127.0.0.1 → connexion refusée. */
    host: true,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
        /** Évite de bufferiser le SSE (/api/robots/stream) — sinon la liste robots ne se met jamais à jour en dev. */
        configure(proxy) {
          proxy.on("proxyRes", (proxyRes, req) => {
            if (req.url?.includes("/stream")) {
              proxyRes.headers["cache-control"] = "no-cache";
              proxyRes.headers["x-accel-buffering"] = "no";
            }
          });
        },
      },
      "/schemas": {
        target: "http://127.0.0.1:3000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: path.resolve(rootDir, "dist/client"),
    emptyOutDir: true,
  },
});
