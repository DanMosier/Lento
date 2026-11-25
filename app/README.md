# Lento app

The Lento app for a PC, phone or tablet. Each feature is a tab.

**Practice:** practise with your own sheet music. Open a MusicXML score, play it back slowly with loops and a
count-in and a metronome (whole notes down to 16ths) and a moving cursor that can allow for headphone delay, record yourself, and see every note colored by intonation and
timing, judged as strictly as you choose (pitch and timing separately).
**Wait mode** is for learning the notes: the cursor stops on each note (showing its name and where it's played)
and moves on only once the microphone hears it held in tune. There's no metronome. After three wrong tries it plays
the note for you. The other shown parts can follow along, and at the end you get a tally of the notes that needed
several tries.

**Library:** browse your score library in Google Drive, open a MusicXML into Practice or a PDF in Drive's viewer, and
queue PDFs (one or a batch) for MusicXML conversion on your PC.
Scores you've opened work offline. Setup: [docs/library.md](../docs/library.md).

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

The app opens on a home screen with a button per feature; the Home button in the header is always there (leaving
Practice with a score open asks first, then closes the score). Each feature is one folder with a `ui.ts` for its
screen. Features never import each other.

- `src/core/` code every feature may use: `score.ts` (MusicXML reading), `app.ts` (saved settings, one shared
  AudioContext, the open-score hand-off), `sounds.ts` (recorded instrument sounds), `live-pitch.ts` (microphone pitch for the tuner and wait mode), `perf.ts` (timing marks), and
  `library/` (the Google Drive library: `model.ts`, `drive.ts`, `library.ts`, `auth.ts`, and `connection.ts`, the one
  connection Library, Convert and Settings share).
- `src/practice/` Practice: `pitch.ts` (YIN pitch tracking, in a worker), `align.ts` and `analyze.ts` (ports of
  `lento_practice` in Python, which stays the reference), `report.ts`, `player.ts` (playback and metronome),
  `parts.ts` (the part picker), `wait.ts` (wait mode's judging), `recorder.ts`, `latency.ts`, `ui.ts`.
- `src/library/` Library: browse and open scores. It hands a score to Practice with `requestOpenScore` from core.
- `src/convert/` Convert PDF: queue PDFs for the PC's watcher and show its status.
- `src/tuner/` Tuner. `src/settings/` Settings (library connection, tuning, headphone delay, sounds).
- `src/main.ts` the shell. To add a feature, add a folder, a home card and a view in `index.html`.

## Instrument sounds

`public/sounds/` holds one small Opus file per instrument and loudness layer, built from VS Chamber Orchestra:
Community Edition (CC0) by `scripts/build_sounds.py` (see its header to rebuild). VSCO records about every third
semitone; the app pitch-shifts the notes between and loops a crossfaded stretch of sustained instruments. Packs
download only when an open score needs them, in the background, and stay in Cache Storage for offline use; playback
uses the synth until they arrive. Phones get one layer (about 80-460 KB per instrument), desktops two.

## Speed

Responsiveness comes first: a feature that makes the app noticeably slower gets reworked or dropped.
`npm run build && npm run perf` drives the built app in Chromium with the CPU slowed 4x (about a mid-range phone)
and checks startup, bundle size, tab switching, opening scores, starting playback and checking a 3-minute recording
against `perf/budgets.json`. CI runs it on every pull request, and main only deploys when it passes.
Heavy parts load late: the score renderer loads when you press Open score, sound packs when a score needs them, and
pitch tracking runs in a Web Worker so the page keeps responding. `node perf/score.mjs <file> [part] [other parts]`
times any real score.

## Publishing

`.github/workflows/app.yml` tests and builds on every pull request that touches `app/`, and publishes `main` to
https://danmosier.github.io/Lento/ (Settings > Pages > Source: GitHub Actions).
