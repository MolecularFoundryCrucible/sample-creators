import react from "@vitejs/plugin-react"
import prefixSelector from "postcss-prefix-selector"
import { defineConfig } from "vitest/config"

// Built files go to ../static/dist and are served by Flask; templates find the hashed file
// names through .vite/manifest.json (see vite_entry() in app.py). A relative base keeps
// chunk imports working under any SCRIPT_NAME prefix.
export default defineConfig({
  base: "./",
  plugins: [react()],
  css: {
    postcss: {
      plugins: [
        // The React islands bring manual-synthesis-ui's global stylesheet (*, .btn, .container,
        // ...). Scope it to the island's root element so it can't restyle the rest of the page.
        prefixSelector({
          prefix: ".ms-island",
          includeFiles: [/manual-synthesis/],
          transform: (prefix: string, selector: string, prefixed: string) =>
            /^(html|body|:root)$/.test(selector) ? prefix : prefixed,
        }),
      ],
    },
  },
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: {
        upload: "src/upload/index.ts",
        synthesis: "src/manual-synthesis/synthesis-entry.jsx",
        traveler: "src/manual-synthesis/traveler-entry.jsx",
        instrument: "src/parsers/index.ts",
      },
    },
  },
  test: {
    environment: "node",
  },
})
