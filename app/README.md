# Lento app

The Lento app for a PC, phone or tablet. Each feature is a tab.

**Practice:** practise with your own sheet music. Open a MusicXML score, play it back slowly with loops and a
count-in and a metronome (whole notes down to 16ths), record yourself, and see every note colored by intonation and
timing, judged as strictly as you choose (pitch and timing separately).

**Tuner:** live note and cents from the microphone, with reference tones for the open strings.

It installs as an app (PWA), works offline, and keeps everything on the device.

```bash
npm install
npm run dev      # http://localhost:5173
npm test         # analyzer tests on synthetic cello takes
npm run build    # static site in dist/
```

The microphone needs https (or localhost). To try it on a phone during development, run `npm run dev -- --host` and open
the https site from `npm run build` + GitHub Pages instead, or use a tunnel.

## Layout

Each feature is one folder with a `ui.ts` for its tab. Features never import each other.

- `src/core/` code every feature may use: `score.ts` (MusicXML reading) and `app.ts` (saved settings, one shared
  AudioContext).
- `src/practice/` the Practice tab: `pitch.ts` (YIN pitch tracking), `align.ts` and `analyze.ts` (ports of
  `lento_practice` in Python, which stays the reference), `report.ts`, `player.ts` (Web Audio playback and metronome),
  `recorder.ts`, `ui.ts`.
- `src/tuner/` the Tuner tab: `tuner.ts` (live pitch and reference tones), `ui.ts`.
- `src/main.ts` the app shell: the tabs. To add a feature, add a folder, a tab button and a view in `index.html`.

## Publishing

`.github/workflows/app.yml` tests and builds on every pull request that touches `app/`, and publishes `main` to
https://danmosier.github.io/Lento/ (Settings > Pages > Source: GitHub Actions).
