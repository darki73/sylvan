import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import VueRouter from "vue-router/vite";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "path";

export default defineConfig({
  plugins: [
    VueRouter(),
    vue(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
  build: {
    outDir: resolve(__dirname, "..", "static", "dist"),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:32400",
      "/ws": { target: "ws://127.0.0.1:32400", ws: true },
    },
  },
});
