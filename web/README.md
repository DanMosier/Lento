# Lento web app

Practise with your own sheet music on a PC, phone or tablet. Open a MusicXML score, play it back slowly with loops and a
count-in, record yourself, and see every note colored by intonation and timing. It installs as an app (PWA), works
offline, and keeps everything on the device.

```bash
npm install
npm run dev      # http://localhost:5173
npm test         # analyzer tests on synthetic cello takes
npm run build    # static site in dist/
```

The microphone needs https (or localhost). To try it on a phone during development, run `npm run dev -- --host` and open
the https site from `npm run build` + GitHub Pages instead, or use a tunnel.

## Layout

- `src/core/` code every feature may use (MusicXML reading). Features never import each other.
- `src/practice/` the practice feature: `pitch.ts` (YIN pitch tracking), `align.ts` and `analyze.ts` (ports of
  `lento_practice` in Python, which stays the reference), `report.ts`, `player.ts` (Web Audio playback), `recorder.ts`.
- `src/main.ts` the page.

## Publishing

`.github/workflows/web.yml` tests and builds on every pull request that touches `web/`, and publishes `main` to GitHub
Pages once Pages is switched on (Settings > Pages > Source: GitHub Actions) and the repository variable
`PAGES_ENABLED` is `true`. Pages on a private repository needs a paid GitHub plan; the built `dist/` folder also works
on any static host (Cloudflare Pages, Netlify).
