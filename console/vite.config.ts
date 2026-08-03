import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    // Dev only. In the image the SPA is served by FastAPI from one origin, so there is no
    // CORS anywhere in production (DESIGN.md §11).
    proxy: { "/api": { target: "http://localhost:8000", changeOrigin: true } },
  },
});
