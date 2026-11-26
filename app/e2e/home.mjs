/**
 * Home always gets you home: opens every screen (and the Convert PDF review window, whose embedded PDF viewer adds
 * history entries of its own) and checks that the Home button returns to the home screen each time. On the way it
 * flags the reviewed PDF for splitting and checks it reaches the To split list and can be marked done.
 * Runs the dev server with the Drive library replaced by a stand-in. Exits 1 on a failure.  npm run e2e
 */
import { createServer } from "vite";
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const xml = `<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0"><part-list><score-part id="P1"><part-name>Voice</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes><note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note></measure></part></score-partwise>`;
const server = await createServer({ root, logLevel: "error", server: { port: 4319, strictPort: true } });
await server.listen();
const browser = await chromium.launch();
const failures = [];
try {
  const page = await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  page.on("pageerror", (e) => failures.push(`page error: ${e.message}`));
  // Drive's PDF viewer stand-in: like the real one, it adds a history entry inside the frame
  await page.route("https://drive.example/**", (r) => r.fulfill({ contentType: "text/html", body: '<p>PDF</p><script>history.pushState({}, "", location.href + "#2")</script>' }));
  await page.addInitScript(() => localStorage.setItem("lento.library.folder", JSON.stringify("https://drive.google.com/drive/folders/e2etestfolder")));
  await page.goto("http://localhost:4319/");
  await page.evaluate(async (xml) => {
    const { DriveLibrary } = await import("/src/core/library/library.ts");
    const index = { version: 1, generated: new Date().toISOString(), pieces: [{ id: "a_b", title: "Test Piece", composer: "Test", files: [{ name: "a_b__x.pdf", kind: "pdf", variant: "x", musicxml: "a_b__x.musicxml" }] }] };
    const P = DriveLibrary.prototype;
    P.cachedIndex = P.loadIndex = async () => index;
    P.pcStatus = async () => null;
    P.readRootJson = async () => null;
    P.writeRootJson = async () => {};
    P.open = async (piece, file) => (file.kind === "pdf" ? { link: "https://drive.example/file/d/1/view", offline: false } : { data: new TextEncoder().encode(xml).buffer, offline: false });
  }, xml);

  const home = async (from) => {
    await page.click("#home-btn");
    try {
      await page.waitForSelector("#view-home:not([hidden])", { timeout: 2000 });
    } catch {
      failures.push(`Home didn't go home from ${from}`);
      await page.goto("http://localhost:4319/");
    }
  };
  for (const screen of ["practice", "library", "convert", "tuner", "settings"]) {
    await page.click(`.home-card[data-go="${screen}"]`);
    await page.waitForSelector(`#view-${screen}:not([hidden])`);
    await home(screen);
  }
  await page.click('.home-card[data-go="convert"]');
  await page.click("#cv-tab-review");
  await page.click(".cv-rv-open");
  await page.waitForSelector("#rv-xml svg", { timeout: 15000 });
  await page.waitForTimeout(500); // let the PDF frame load and add its history entry
  await page.click("#rv-next").catch(() => {});
  await page.click("#rv-split");
  if ((await page.getAttribute("#rv-split", "aria-pressed")) !== "true") failures.push("Flag for splitting didn't flag the PDF");
  if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/review-flagged.png` });
  await page.click("#rv-close");
  try {
    await page.waitForSelector("#cv-split-box:not([hidden]) #cv-split-list li:has-text('Test Piece')", { timeout: 2000 });
    if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/split-list.png` });
    await page.click('#cv-split-list button:has-text("Done")');
    await page.waitForSelector("#cv-split-list li.done", { timeout: 2000 });
    if ((await page.textContent("#cv-split-title"))?.includes("(")) failures.push("A PDF marked done still counts as to split");
  } catch {
    failures.push("The flagged PDF didn't show in the To split list, or couldn't be marked done");
  }
  await home("the review window");
} finally {
  await browser.close();
  await server.close();
}
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("Home works from every screen and after a review; Flag for splitting reaches the To split list.");
