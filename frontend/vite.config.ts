import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  server: {
    // لازم نثبّت العنوان: من غيره فيت بيربط على ::1 بس، والمشغّل بينده
    // على 127.0.0.1 فمبيلاقيهوش
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    // الفرونت بينادي /api وفيت بيوجّهها للباك إند — مفيش CORS في التطوير
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
});
