import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    // The dev proxy masks production single-origin routing bugs; the built SPA is served
    // by FastAPI itself, and that path is tested separately.
    proxy: { "/api": { target: "http://127.0.0.1:8770", changeOrigin: true } },
  },
});
