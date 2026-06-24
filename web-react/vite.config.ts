import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  base: "/app/",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/health": "http://127.0.0.1:9651",
      "/api": "http://127.0.0.1:9651",
      "/chat": "http://127.0.0.1:9651",
      "/approve": "http://127.0.0.1:9651",
      "/cancel": "http://127.0.0.1:9651",
      "/upload": "http://127.0.0.1:9651",
      "/model": "http://127.0.0.1:9651",
      "/profile": "http://127.0.0.1:9651",
      "/profiles": "http://127.0.0.1:9651",
      "/diff": "http://127.0.0.1:9651",
      "/projects": "http://127.0.0.1:9651",
      "/skills": "http://127.0.0.1:9651",
      "/kanban": "http://127.0.0.1:9651",
      "/sessions": "http://127.0.0.1:9651",
      "/memory": "http://127.0.0.1:9651",
      "/analytics": "http://127.0.0.1:9651",
      "/selflearning": "http://127.0.0.1:9651",
      "/cron": "http://127.0.0.1:9651",
      "/auth": "http://127.0.0.1:9651",
      "/subscription": "http://127.0.0.1:9651",
      "/promo": "http://127.0.0.1:9651",
      "/benchmarks": "http://127.0.0.1:9651",
      "/admin": "http://127.0.0.1:9651",
      "/company": "http://127.0.0.1:9651",
    },
  },
});
