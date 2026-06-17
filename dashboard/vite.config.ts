import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard is a read-only client of the crucible API. In dev, proxy API
// calls to the FastAPI server so the SPA and API share an origin.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/runs": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
});
