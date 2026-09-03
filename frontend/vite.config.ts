import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/conversations": "http://localhost:8000",
      "/auth/login": "http://localhost:8000",
      // Chaves específicas (não "/ops") — o proxy do Vite casa por prefixo, e
      // "/ops" bateria também no document request de quem digita a URL
      // /ops no navegador, quebrando a SPA. Backend só expõe estes subpaths
      // (src/app/api/routes/ops.py): overview, turns (+ turns/:id) e eval.
      "/ops/overview": "http://localhost:8000",
      "/ops/turns": "http://localhost:8000",
      "/ops/eval": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
