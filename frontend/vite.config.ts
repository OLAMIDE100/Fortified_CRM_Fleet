import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://backend.fortified-crm-fleet.svc.cluster.local:8000",
      "/health": "http://backend.fortified-crm-fleet.svc.cluster.local:8000",
    },
  },
});
