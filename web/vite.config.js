import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" so the built bundle works on any static host (GitHub Pages subpath, Vercel, file).
export default defineConfig({
  plugins: [react()],
  base: "./",
});
