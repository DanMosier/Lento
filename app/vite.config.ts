import { defineConfig, type Plugin } from "vite";
import { VitePWA } from "vite-plugin-pwa";
import { execSync } from "node:child_process";

// The version shown in Settings: the commit it was built from, and when. version.json (not cached by the app) lets
// an open copy of the app notice that a newer one has been published.
const commit = (() => {
  if (process.env.GITHUB_SHA) return process.env.GITHUB_SHA.slice(0, 7);
  try {
    return execSync("git rev-parse --short=7 HEAD", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
  } catch {
    return "dev";
  }
})();
const built = new Date().toISOString();
const versionFile = (): Plugin => ({
  name: "lento-version",
  apply: "build",
  generateBundle() {
    this.emitFile({ type: "asset", fileName: "version.json", source: JSON.stringify({ commit, built }) });
  },
});

// base "./" so the build works from any folder, including GitHub Pages (/Lento/)
export default defineConfig({
  base: "./",
  build: { chunkSizeWarningLimit: 2000 },
  define: { __LENTO_COMMIT__: JSON.stringify(commit), __LENTO_BUILT__: JSON.stringify(built) },
  plugins: [
    versionFile(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icon.svg"],
      manifest: {
        name: "Lento",
        short_name: "Lento",
        description: "Practise with your sheet music: slowed playback, loops, a metronome, a tuner, and note-by-note intonation and timing feedback.",
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
