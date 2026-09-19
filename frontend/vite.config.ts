import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true, // bind IPv4 + IPv6 so both 127.0.0.1 and localhost work
    port: 5173,
    strictPort: true,
  },
});
