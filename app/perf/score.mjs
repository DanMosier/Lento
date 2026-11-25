/**
 * Speed check on one real score file: how long the Practice tab takes to open it, switch parts, start playback,
 * keep the cursor moving, and switch tabs with it loaded. Same phone-speed CPU as perf/run.mjs. Reports only;
 * it has no budgets, because real scores vary too much.
 *
 *   npm run build && node perf/score.mjs path/to/score.mxl [part name]
 */
import { preview } from "vite";
import { chromium } from "playwright";
import { dirname, join, basename } from "node:path";
import { fileURLToPath } from "node:url";

const file = process.argv[2];
const partName = process.argv[3] ?? "Violoncello";
if (!file) throw new Error("usage: node perf/score.mjs <score.musicxml|.mxl> [part name]");
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const THROTTLE = Number(process.env.THROTTLE ?? 4);

const server = await preview({ root, logLevel: "error", preview: { port: 4180, strictPort: true } });
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const r = [];
const add = (k, v, note = "") => r.push([k, v, note]);
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await (await context.newCDPSession(page)).send("Emulation.setCPUThrottlingRate", { rate: THROTTLE });
  await page.addInitScript(() => {
    window.__long = [];
    new PerformanceObserver((l) => l.getEntries().forEach((e) => window.__long.push([e.startTime, e.duration]))).observe({ type: "longtask", buffered: true });
  });
  const measure = (n) => page.evaluate((n) => performance.getEntriesByName(`lento:${n}`).map((e) => e.duration), n);
  const last = async (n) => (await measure(n)).at(-1);
  const waitFor = (n, c) => page.waitForFunction(([n, c]) => performance.getEntriesByName(`lento:${n}`).length >= c, [n, c], { timeout: 600_000 });
  const now = () => page.evaluate(() => performance.now());
  const longest = (from, to = Infinity) => page.evaluate(([a, b]) => Math.max(0, ...window.__long.filter(([s]) => s >= a && s < b).map(([, d]) => d)), [from, to]);

  await page.goto("http://localhost:4180/");
  await waitFor("ready", 1);

  // Open (first part, as the app picks it)
  let t = await now();
  await page.setInputFiles("#score-file", file);
  await waitFor("open-score", 1);
  add("open score (total)", await last("open-score"));
  add("  parse", await last("parse-score"));
  add("  render", await last("render-score"));
  add("    OSMD load", await last("load-sheet"));
  add("    OSMD draw", await last("draw-sheet"));
  add("  longest freeze while opening", await longest(t));
  add(`  opened part: ${await page.evaluate(() => document.querySelector("#part").selectedOptions[0]?.textContent)}`, 0, "count");
  add("  parts found", await page.evaluate(() => document.querySelectorAll("#part option").length), "count");

  // Switch to the cello part
  const value = await page.evaluate((name) => [...document.querySelectorAll("#part option")].find((o) => o.textContent.trim() === name)?.value, partName);
  if (value) {
    t = await now();
    await page.evaluate((v) => { const s = document.querySelector("#part"); s.value = v; s.dispatchEvent(new Event("change")); }, value);
    await waitFor("open-score", 2);
    add(`switch part to ${partName}`, await last("open-score"));
    add("  longest freeze", await longest(t));
  }
  add("page elements after render", await page.evaluate(() => document.getElementsByTagName("*").length), "count");

  // Playback: start, then 8 s of cursor movement
  await page.click("#play");
  await waitFor("start-playback", 1);
  add("start playback", await last("start-playback"));
  const frames = await page.evaluate(
    () =>
      new Promise((res) => {
        const gaps = [];
        let prev = performance.now();
        const end = prev + 8000;
        const tick = (ts) => {
          gaps.push(ts - prev);
          prev = ts;
          if (ts < end) requestAnimationFrame(tick);
          else res(gaps);
        };
        requestAnimationFrame(tick);
      }),
  );
  await page.click("#play");
  frames.sort((a, b) => a - b);
  add("playback frames per second", frames.length / 8, "fps");
  add("  worst frame during playback", frames.at(-1));
  add("  frames slower than 50 ms", frames.filter((g) => g > 50).length, "count");

  // Tab switch with the big score loaded
  const tabMs = await page.evaluate(async () => {
    const tab = (n) => document.querySelector(`[data-tab="${n}"]`);
    const frame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const t0 = performance.now();
    tab("tuner").click();
    await frame();
    tab("practice").click();
    await frame();
    return (performance.now() - t0) / 2;
  });
  add("tab switch with score loaded", tabMs);
  if (errors.length) add(`page errors: ${errors.join(" | ")}`, 0, "count");
} finally {
  await browser.close();
  await new Promise((res) => server.httpServer.close(res));
}

console.log(`\n${basename(file)} at ${THROTTLE}x slower CPU (about a mid-range phone)\n`);
for (const [k, v, unit] of r) console.log(`${k.padEnd(40)} ${unit === "count" ? v : unit === "fps" ? `${v.toFixed(0)} fps` : `${Math.round(v)} ms`}`);
