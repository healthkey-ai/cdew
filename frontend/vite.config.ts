import dns from "node:dns";
import path from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Resolve `localhost` to IPv4 first — Django's dev server binds IPv4 only, so
// without this the proxy gets ECONNREFUSED on ::1.
dns.setDefaultResultOrder("ipv4first");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: { "@": path.resolve(__dirname, "./src") },
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": { target: apiProxyTarget, changeOrigin: true },
      },
    },
  };
});
