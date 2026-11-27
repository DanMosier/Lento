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
import { scoreXml, takeWav, sheetPdf } from "./fixtures.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const budgets = JSON.parse(readFileSync(join(here, "budgets.json"), "utf8"));
const THROTTLE = Number(process.env.THROTTLE ?? 4);

const tmp = mkdtempSync(join(tmpdir(), "lento-perf-"));
const TAKE_MEASURES = 90; // 3 minutes at 120 bpm
const BIG_MEASURES = 400;
const REVIEW_MEASURES = 1500; // about the length of a converted sonata with its piano part
writeFileSync(join(tmp, "take-score.musicxml"), scoreXml(TAKE_MEASURES, 120, "Three minute piece"));
writeFileSync(join(tmp, "big-score.musicxml"), scoreXml(BIG_MEASURES, 120, "Long piece"));
writeFileSync(join(tmp, "take.wav"), takeWav(TAKE_MEASURES));
writeFileSync(join(tmp, "book.pdf"), sheetPdf(80, [1, 9, 17, 30, 44, 61])); // an 80-page book of six pieces, for the splitter
writeFileSync(join(tmp, "mic.wav"), takeWav(12, 120, 48000)); // what the fake microphone "plays" in wait mode

// ---- bundle size: what the phone downloads before the app can start ----
const html = readFileSync(join(root, "dist", "index.html"), "utf8");
const entry = [...html.matchAll(/<script[^>]+src="\.?\/?([^"]+\.js)"/g)].map((m) => m[1]);
const preloads = [...html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="\.?\/?([^"]+\.js)"/g)].map((m) => m[1]);
const gz = (f) => gzipSync(readFileSync(join(root, "dist", f))).length / 1024;
const startupKb = [...entry, ...preloads].reduce((s, f) => s + gz(f), 0);
// The SoundFont synthesizer downloads only for people who choose "My own SoundFont", so it has a budget of its own.
const optional = (f) => /^(soundfont-|spessasynth_processor)/.test(f);
const jsFiles = readdirSync(join(root, "dist", "assets")).filter((f) => f.endsWith(".js"));
const allJsKb = jsFiles.filter((f) => !optional(f)).reduce((s, f) => s + gz(join("assets", f)), 0);
const soundfontJsKb = jsFiles.filter(optional).reduce((s, f) => s + gz(join("assets", f)), 0);

const server = await preview({ root, logLevel: "error", preview: { port: 4179, strictPort: true } });
const browser = await chromium.launch({
  ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
  args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${join(tmp, "mic.wav")}`],
});
const results = { "startup-js-kb": startupKb, "all-js-kb": allJsKb, "soundfont-js-kb": soundfontJsKb };
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
  const waitForMark = (n) => page.waitForFunction((n) => performance.getEntriesByName(`lento:${n}`).length > 0, n);
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
  await waitForMark("entered-practice");
  results["first-open-practice-ms"] = (await measure("load-practice"))[0]; // its code loads the first time
  await page.setInputFiles("#score-file", join(tmp, "take-score.musicxml"));
  await waitFor("open-score", 1);
  results["open-score-ms"] = (await measure("open-score"))[0];
  let t = await now();
  await page.setInputFiles("#score-file", join(tmp, "big-score.musicxml"));
  await waitFor("open-score", 2);
  results["open-big-score-ms"] = (await measure("open-score"))[1];
  results["open-big-score-longest-block-ms"] = await longestTask(t);

  // 3b. Laying a long score out again holds the page for seconds, so it must never happen by itself: not when
  // the phone's address bar slides away, not when the phone is turned (which resizes the page a few times in a
  // row), not when playback stops. Turning the phone offers "Fit to screen" instead; pressing it lays out once.
  await page.setViewportSize({ width: 390, height: 780 });
  await page.waitForTimeout(600);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(1200);
  results["address-bar-relayouts"] = (await measure("relayout-score")).length;
  for (const w of [844, 880, 915]) {
    await page.setViewportSize({ width: w, height: 390 });
    await page.waitForTimeout(200);
  }
  await page.waitForTimeout(1500);
  await page.click("#play");
  await waitFor("start-playback", 1);
  await page.waitForTimeout(1000);
  await page.click("#play");
  await page.waitForTimeout(1500);
  results["unasked-relayouts"] = (await measure("relayout-score")).length;
  await page.click("#fit-btn");
  await waitFor("relayout-score", 1);
  results["fit-big-score-ms"] = (await measure("relayout-score"))[0];
  await page.waitForTimeout(500);
  results["fit-relayouts"] = (await measure("relayout-score")).length;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(1500);
  await page.click("#fit-btn");
  await waitFor("relayout-score", 2);

  // 3c. Tap a note of the long score to play from it: finding the note and starting must feel instant
  await page.waitForTimeout(800);
  const head = await page.evaluate(() => {
    const h = [...document.querySelectorAll("#sheet svg g.vf-notehead")][40];
    h.scrollIntoView({ block: "center" });
    const r = h.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  });
  t = await now();
  await page.mouse.click(head.x, head.y);
  await waitFor("start-playback", 2);
  results["tap-note-ms"] = (await measure("find-tapped-note"))[0] + (await measure("start-playback"))[1];
  results["tap-note-longest-block-ms"] = await longestTask(t);
  await page.waitForTimeout(500);
  await page.click("#play");

  // 4. Start and stop playback on the 3-minute score
  await page.setInputFiles("#score-file", join(tmp, "take-score.musicxml"));
  await waitFor("open-score", 3);
  await page.click("#play");
  await waitFor("start-playback", 3);
  results["start-playback-ms"] = (await measure("start-playback"))[2];
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

  // 5b. Transposing and changing the clef redraw the score from a changed copy; that must cost no more than opening it
  const opened = (await measure("open-score")).length;
  await page.selectOption("#transpose", "2");
  await waitFor("open-score", opened + 1);
  await page.selectOption("#clef", "tenor");
  await waitFor("open-score", opened + 2);
  const views = (await measure("open-score")).slice(opened);
  results["transpose-score-ms"] = views[0];
  results["change-clef-ms"] = views[1];
  if (!(await page.textContent("#status")).includes("up a whole step")) errors.push("transposing didn't say so in the status line");

  // 6. The Library table with a library the size of Daniel's (2,251 pieces): draw, sort, search, scroll
  const comps = ["Bach, Johann Sebastian", "Popper, David", "Fauré, Gabriel", "Saint-Saëns, Camille", "Lalo, Édouard", "Davidov, Karl", "Romberg, Bernhard"];
  const pieces = Array.from({ length: 2251 }, (_, i) => ({
    id: `p${i}_x`, title: `Piece ${i} in ${"CDGA"[i % 4]} major, Op. ${i % 90}`, composer: comps[i % 7], genre: ["Baroque", "Romantic", "Classical / Romantic"][i % 3],
    year: String(1700 + ((i * 7) % 300)), instrumentation: ["Duet (Cello & Piano)", "Solo Cello"][i % 2], tags: i % 5 ? undefined : ["legato"],
    files: [{ name: `p${i}_x__cello.pdf`, kind: "pdf", variant: "cello", ...(i % 6 ? {} : { musicxml: `p${i}_x__cello.musicxml` }) }, { name: `p${i}_x__piano.pdf`, kind: "pdf", variant: "piano" }],
  }));
  await page.evaluate(async (idx) => {
    localStorage.setItem("lento.library.folder", JSON.stringify("https://drive.google.com/drive/folders/perfTestFolder0000000"));
    // 300 favorites and 40 setlists of 25 pieces, more than anyone keeps, so the Favorites tab is measured at size
    const favorites = {};
    for (let i = 0; i < 2251; i += 7) favorites[`p${i}_x`] = { on: true, at: 1 };
    const setlists = {};
    for (let s = 0; s < 40; s++)
      setlists[`s${s}`] = { id: `s${s}`, name: `Setlist ${s}`, pieces: Array.from({ length: 25 }, (_, k) => `p${s * 25 + k}_x`), created: s, updated: s };
    localStorage.setItem("lento.library.lists", JSON.stringify({ format: "lento-lists", version: 1, favorites, setlists }));
    await new Promise((res) => {
      const r = indexedDB.open("lento-library", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("files");
      r.onsuccess = () => {
        const tx = r.result.transaction("files", "readwrite");
        tx.objectStore("files").put({ data: new TextEncoder().encode(JSON.stringify(idx)), modifiedTime: "x" }, "library.json");
        tx.oncomplete = res;
      };
    });
  }, { format: "lento-library", version: 1, generated: new Date().toISOString(), pieces });
  await page.goto("http://localhost:4179/"); // a fresh start, so the measures below are the library's alone
  await waitFor("ready");
  await page.click('.home-card[data-go="library"]');
  await waitFor("library-render", 1);
  await page.click("#lib-head [role=columnheader]:nth-child(4) button"); // sort by year
  await waitFor("library-render", 2);
  await page.fill("#lib-search", "major romantic");
  await waitFor("library-render", 3);
  results["library-render-ms"] = Math.max(...(await measure("library-render")));
  await page.fill("#lib-search", "");
  await waitFor("library-render", 4);
  t = await now();
  // a fast fling: 600 px a frame for a second and a half, done inside the page like a real scroll
  await page.evaluate(async () => {
    const el = document.getElementById("lib-table");
    for (let i = 1; i <= 90; i++) {
      el.scrollTop = i * 600;
      await new Promise((r) => requestAnimationFrame(r));
    }
  });
  await page.waitForTimeout(200);
  results["library-scroll-longest-block-ms"] = await longestTask(t);
  // favorites: star a row, then switch to the Favorites tab; open the Setlists window and one setlist
  t = await now();
  await page.click("#lib-body .lib-row:nth-child(3) .lib-star");
  await page.click("#lib-tab-fav");
  await waitFor("library-render", 5);
  results["library-favorites-ms"] = (await measure("library-render")).at(-1);
  await page.click("#lib-sets-open");
  await page.click("#lib-sets-body .sets-item");
  await page.waitForSelector("#lib-sets-body .sets-pieces");
  await page.click("#lib-sets-close");
  await page.click("#lib-tab-all");
  await waitFor("library-render", 6);
  results["library-lists-longest-block-ms"] = await longestTask(t);

  // 7. The Convert PDF Review window on a long converted score: open it, then the next page of bars. Drive isn't
  // reachable here, so the library's offline copies are used.
  await page.route(/googleapis\.com|accounts\.google\.com|drive\.google\.com/, (r) => r.abort());
  await page.evaluate(async ([idx, xml]) => {
    await new Promise((res) => {
      const r = indexedDB.open("lento-library", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("files");
      r.onsuccess = () => {
        const tx = r.result.transaction("files", "readwrite");
        const put = (key, text) => tx.objectStore("files").put({ data: new TextEncoder().encode(text).buffer, modifiedTime: "x" }, key);
        put("library.json", JSON.stringify(idx));
        put("pieces/rv_x/rv_x__score.musicxml", xml);
        tx.oncomplete = res;
      };
    });
  }, [
    { format: "lento-library", version: 1, generated: new Date().toISOString(), pieces: [{ id: "rv_x", title: "Long sonata", composer: "Test", files: [{ name: "rv_x__score.pdf", kind: "pdf", variant: "score", musicxml: "rv_x__score.musicxml" }] }] },
    scoreXml(REVIEW_MEASURES, 120, "Long sonata"),
  ]);
  await page.goto("http://localhost:4179/");
  await waitFor("ready");
  await page.click('.home-card[data-go="convert"]');
  await page.click("#cv-tab-review");
  t = await now();
  await page.click(".cv-rv-open", { timeout: 20_000 });
  await waitFor("review-draw", 1);
  results["review-big-score-ms"] = (await now()) - t;
  results["review-big-score-longest-block-ms"] = await longestTask(t);
  t = await now();
  await page.click("#rv-bars-next");
  await waitFor("review-draw", 2);
  results["review-page-ms"] = (await measure("review-draw"))[1];
  results["review-page-longest-block-ms"] = await longestTask(t);
  if (await page.isVisible("#rv-xml-msg")) errors.push(`Review: ${await page.textContent("#rv-xml-msg")}`);

  // 8. The PDF splitter: open an 80-page book (its code and pdf.js load the first time), draw the first pages, mark
  // a piece, and make the PDFs. The page must stay responsive while pages draw.
  await page.click("#rv-close");
  await page.click("#cv-split-open");
  t = await now();
  await page.setInputFiles("#cv-split-file", join(tmp, "book.pdf"));
  await waitFor("split-open");
  results["split-open-ms"] = (await measure("split-open"))[0];
  await page.waitForFunction(() => document.querySelectorAll(".sp-page").length === 80);
  await page.waitForTimeout(1500); // pages drawing
  await page.click('.sp-page[data-page="5"]');
  await page.evaluate(async () => {
    const el = document.getElementById("sp-grid");
    for (let i = 1; i <= 40; i++) {
      el.scrollTop = i * 150;
      await new Promise((r) => requestAnimationFrame(r));
    }
  });
  await page.waitForTimeout(1000);
  results["split-longest-block-ms"] = await longestTask(t);
  if ((await page.$$(".sp-parts li")).length !== 7) errors.push("the splitter didn't find six bookmarked pieces plus the one marked");
  const download = page.waitForEvent("download");
  await page.click("#sp-download");
  if (!(await download).suggestedFilename().endsWith("(split).zip")) errors.push("the splitter's download isn't the zip of pieces");
  await page.click("#sp-close");
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
const unit = (k) => (k.endsWith("kb") ? "KB gz" : k.endsWith("relayouts") ? "times" : "ms");
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
