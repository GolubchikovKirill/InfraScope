import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Libraries in their own long-lived chunks, so a deploy that only
        // touches app code leaves them in every browser's cache. The object
        // form matched package entry points only: react-dom/client and the
        // scheduler - most of React - ended up in the app chunk and were
        // re-downloaded after every release.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (/node_modules\/(react|react-dom|scheduler|react-router|react-router-dom|cookie|set-cookie-parser)\//.test(id)) {
            return "react-vendor";
          }
          if (id.includes("node_modules/@tanstack/")) return "query";
          if (id.includes("node_modules/axios/")) return "http";
          return undefined;
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    css: true,
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["e2e/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      include: ["src/**/*.{ts,tsx}"],
    },
  },
});
