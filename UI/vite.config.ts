import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build goes into the Python package, so `ventureos-api` serves the UI with no Node.js.
// In development, `npm run dev` proxies /api to the running backend.
export default defineConfig({
  plugins: [react()],
  build: { outDir: "../src/pipeline/static", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { "/api": process.env.VENTUREOS_API_URL ?? "http://127.0.0.1:8000" },
  },
});
