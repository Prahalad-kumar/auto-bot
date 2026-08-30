import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const apiUrl = (env.VITE_API_URL || "http://backend:8000").replace(/\/$/, "");

  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/api": {
          target: apiUrl,
          changeOrigin: true,
        },
      },
    },
  };
});
