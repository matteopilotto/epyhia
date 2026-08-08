import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    // Dev only. In the image the SPA is served by FastAPI from one origin, so there is no
    // CORS anywhere in production (DESIGN.md §11), and the dev server has to stand in for
    // that or the console would need a second way in.
    //
    // The prefix is stripped again before forwarding, so the API keeps its own paths and
    // never learns that a dev server exists. Prefixing rather than listing `/runs`,
    // `/briefs`, `/actions`, … is what keeps this from needing an edit every time a router
    // is added — a proxy that silently stops covering a new route would fail as a blank
    // page rather than as an error.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
