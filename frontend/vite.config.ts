import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";
import basicSsl from "@vitejs/plugin-basic-ssl";
import mkcert from "vite-plugin-mkcert";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  server: {
    // Bind to all interfaces so phones on the network can reach dev server.
    host: true,
    port: 8080,
    // Camera APIs require a secure context on mobile (HTTPS or localhost).
    https: mode === "development",
    hmr: {
      overlay: false,
    },
  },
  plugins: [
    react(),
    mode === "development" && componentTagger(),
    // Optional: locally-trusted certs via mkcert (no auto-download).
    // Enable with: `ORBIT_MKCERT=1 npm run dev` after installing mkcert.
    mode === "development" &&
      process.env.ORBIT_MKCERT === "1" &&
      mkcert({
        autoUpgrade: false,
        mkcertPath: "mkcert",
        savePath: path.resolve(__dirname, ".vite-plugin-mkcert"),
      }),
    // Fallback to a basic self-signed cert if mkcert isn't set up.
    mode === "development" && basicSsl(),
  ].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
}));
