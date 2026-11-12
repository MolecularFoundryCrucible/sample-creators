import { defineConfig } from "vitest/config"

// Built files go to ../static/dist and are served by Flask; templates find the hashed file
// names through .vite/manifest.json (see vite_entry() in app.py). A relative base keeps
// chunk imports working under any SCRIPT_NAME prefix.
export default defineConfig({
  base: "./",
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: {
        upload: "src/upload/index.ts",
      },
    },
  },
  test: {
    environment: "node",
  },
})
