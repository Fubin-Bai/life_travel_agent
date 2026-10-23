import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发环境同源代理；浏览器不需要硬编码后端地址。
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
