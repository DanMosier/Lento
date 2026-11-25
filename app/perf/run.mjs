/**
 * Performance check for the Lento app: builds nothing, serves dist/, drives it in Chromium with the CPU slowed
 * down to roughly a mid-range phone, and compares each timing with perf/budgets.json. Exits 1 if any is over.
 *
 *   npm run build && npm run perf            (THROTTLE=4 by default; THROTTLE=1 for your own machine's speed)
 */
import { mkdtempSync, readFileSync, writeFileSync, appendFileSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";
import { preview } from "vite";
import { chromium } from "playwright";
import { scoreXml, takeWav } from "./fixtures.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const budgets = JSON.parse(readFileSync(join(here, "budgets.json"), "utf8"));
const THROTTLE = Number(process.env.THROTTLE ?? 4);

const tmp = mkdtempSync(join(tmpdir(), "lento-perf-"));
const TAKE_MEASURES = 90; // 3 minutes at 120 bpm
const BIG_MEASURES = 400;
writeFileSync(join(tmp, "take-score.musicxml"), scoreXml(TAKE_MEASURES, 120, "Three minute piece"));
writeFileSync(join(tmp, "big-score.musicxml"), scoreXml(BIG_MEASURES, 120, "Long piece"));
writeFileSync(join(tmp, "take.wav"), takeWav(TAKE_MEASURES));
writeFileSync(join(tmp, "mic.wav"), takeWav(12, 120, 48000)); // what the fake microphone "plays" in wait mode

// ---- bundle size: what the phone downloads before the app can start ----
const html = readFileSync(join(root, "dist", "index.html"), "utf8");
const entry = [...html.matchAll(/<script[^>]+src="\.?\/?([^"]+\.js)"/g)].map((m) => m[1]);
const preloads = [...html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="\.?\/?([^"]+\.js)"/g)].map((m) => m[1]);
const gz = (f) => gzipSync(readFileSync(join(root, "dist", f))).length / 1024;
const startupKb = [...entry, ...preloads].reduce((s, f) => s + gz(f), 0);
const allJsKb = readdirSync(join(root, "dist", "assets")).filter((f) => f.endsWith(".js")).reduce((s, f) => s + gz(join("assets", f)), 0);

const server = await preview({ root, logLevel: "error", preview: { port: 4179, strictPort: true } });
const browser = await chromium.launch({
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${join(tmp, "mic.wav")}`],
});
const results = { "startup-js-kb": startupKb, "all-js-kb": allJsKb };
const errors = [];
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  const cdp = await context.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: THROTTLE });
  await page.addInitScript(() => {
    window.__long = [];
    try {
      new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__long.push([e.startTime, e.duration]))).observe({ type: "longtask", buffered: true });
    } catch {}
  });
  const measure = (name) => page.evaluate((n) => performance.getEntriesByName(`lento:${n}`).map((e) => e.duration), name);
  const waitFor = (name, count = 1, timeout = 180_000) =>
    page.waitForFunction(([n, c]) => performance.getEntriesByName(`lento:${n}`).length >= c, [name, count], { timeout });
  const longestTask = (from) => page.evaluate((t) => Math.max(0, ...window.__long.filter(([s]) => s >= t).map(([, d]) => d)), from);
  const now = () => page.evaluate(() => performance.now());

  // 1. Startup: navigation start to the app being usable
  await page.goto("http://localhost:4179/");
  await waitFor("ready");
  results["startup-ms"] = await page.evaluate(() => performance.getEntriesByName("lento:ready")[0].startTime);

  // 2. Switching tabs
  results["tab-switch-ms"] = await page.evaluate(async () => {
    // home -> Tuner -> back home
    const frame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const t0 = performance.now();
    document.querySelector('.home-card[data-go="tuner"]').click();
    await frame();
    document.getElementById("home-btn").click();
    while (document.getElementById("view-home").hidden) await new Promise((r) => requestAnimationFrame(r)); // Home goes back through history
    await frame();
    return (performance.now() - t0) / 2;
  });

  // 3. Opening a 3-minute score, then a 400-measure score
  await page.click('.home-card[data-go="practice"]');
  await page.setInputFiles("#score-file", join(tmp, "take-score.musicxml"));
  await waitFor("open-score", 1);
  results["open-score-ms"] = (await measure("open-score"))[0];
  let t = await now();
  await page.setInputFiles("#score-file", join(tmp, "big-score.musicxml"));
  await waitFor("open-score", 2);
  results["open-big-score-ms"] = (await measure("open-score"))[1];
  results["open-big-score-longest-block-ms"] = await longestTask(t);

  // 4. Start and stop playback on the 3-minute score
  await page.setInputFiles("#score-file", join(tmp, "take-score.musicxml"));
  await waitFor("open-score", 3);
  await page.click("#play");
  await waitFor("start-playback", 1);
  results["start-playback-ms"] = (await measure("start-playback"))[0];
  await page.waitForTimeout(500);
  await page.click("#play");

  // 4b. Wait mode: the microphone is read 25 times a second while the cursor waits; the page must stay responsive
  t = await now();
  await page.click("#wait");
  await page.waitForSelector("#wait-panel:not([hidden])");
  await page.waitForTimeout(4000);
  results["wait-mode-longest-block-ms"] = await longestTask(t);
  const found = await page.evaluate(() => parseInt(document.getElementById("wait-progress").textContent) - 1);
  if (!(found > 0)) errors.push("wait mode heard no notes from the test microphone");
  await page.click("#wait-stop");

  // 5. Checking a 3-minute recording
  t = await now();
  await page.setInputFiles("#audio-file", join(tmp, "take.wav"));
  await waitFor("check", 1);
  results["check-3min-ms"] = (await measure("check"))[0];
  results["check-3min-longest-block-ms"] = await longestTask(t);
  results["  load-sound-pack-ms"] = (await measure("load-sound")).at(-1);
  for (const step of ["decode-audio", "track-pitch", "analyze", "render-score"]) {
    const d = await measure(step);
    results[`  ${step}-ms`] = d[d.length - 1];
  }
} finally {
  await browser.close();
  await new Promise((r) => server.httpServer.close(r));
}

// ---- report ----
const rows = Object.entries(results).map(([k, v]) => {
  const limit = budgets[k.trim()];
  const over = limit !== undefined && v > limit;
  return { k, v, limit, over };
});
const unit = (k) => (k.endsWith("kb") ? "KB gz" : "ms");
const lines = [
  `### Lento performance (CPU slowed ${THROTTLE}x)`,
  "",
  "| Measure | Result | Budget | |",
  "| --- | ---: | ---: | --- |",
  ...rows.map((r) => `| ${r.k.trim()} | ${Math.round(r.v)} ${unit(r.k)} | ${r.limit === undefined ? "" : `${r.limit} ${unit(r.k)}`} | ${r.limit === undefined ? "" : r.over ? "OVER" : "ok"} |`),
];
lines.push(
  "",
  "Times are on the page with the CPU slowed down, except pitch tracking, which runs in a worker that the slowdown " +
    "doesn't reach. \"Longest block\" is the longest time the page could not respond to a tap. Budgets: perf/budgets.json.",
);
if (errors.length) lines.push("", `Page errors: ${errors.join("; ")}`);
const report = lines.join("\n");
console.log(report);
writeFileSync(join(here, "report.md"), report + "\n");
if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, report + "\n");
process.exit(rows.some((r) => r.over) || errors.length ? 1 : 0);
