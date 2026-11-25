import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// base "./" so the build works from any folder, including GitHub Pages (/Lento/)
export default defineConfig({
  base: "./",
  build: { chunkSizeWarningLimit: 2000 },
  plugins: [
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icon.svg"],
      manifest: {
        name: "Lento practice",
        short_name: "Lento",
        description: "Practise with your sheet music: slowed playback, loops, and note-by-note intonation and timing feedback.",
        theme_color: "#7a3e1d",
        background_color: "#faf7f2",
        display: "standalone",
        start_url: ".",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: { globPatterns: ["**/*.{js,css,html,svg,png}"], maximumFileSizeToCacheInBytes: 6_000_000 },
    }),
  ],
});
