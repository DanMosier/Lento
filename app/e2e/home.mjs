/**
 * Home always gets you home: opens every screen (and the Convert PDF review window, whose embedded PDF viewer adds
 * history entries of its own) and checks that the Home button returns to the home screen each time. On the way it
 * flags a PDF for splitting and checks it moves to the bottom of the Review list, reaches the To split screen, and
 * can be marked done there. A conversion the converter flagged shows its Check badge and what the converter found.
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
    const index = { version: 1, generated: new Date().toISOString(), pieces: [{ id: "a_b", title: "Test Piece", composer: "Test", files: [{ name: "a_b__x.pdf", kind: "pdf", variant: "x", musicxml: "a_b__x.musicxml" }] }, { id: "c_d", title: "Other Piece", composer: "Test", files: [{ name: "c_d__x.pdf", kind: "pdf", variant: "x", musicxml: "c_d__x.musicxml", quality: "REVIEW", quality_note: "left out 116 slurs and 2 octave lines (8va) that did not start or end properly" }] }] };
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
  // A score opened from the Library: the piece's window must not stay open (invisible, but modal) behind Practice,
  // where it blocked every button, Home included.
  await page.click('.home-card[data-go="library"]');
  await page.click(".lib-body .lib-row");
  await page.click('#lib-detail button:has-text("Practice")');
  await page.waitForFunction(() => performance.getEntriesByName("lento:open-score").length, null, { timeout: 15000 });
  if (await page.evaluate(() => [...document.querySelectorAll("dialog")].some((d) => d.open)))
    failures.push("A window stayed open after opening a score from the Library");
  try {
    await page.click("#play", { timeout: 3000 });
    await page.click("#play", { timeout: 3000 });
  } catch {
    failures.push("Practice buttons didn't respond after opening a score from the Library");
  }
  try {
    await page.click("#home-btn", { timeout: 3000 });
    await page.click('#leave-dialog button[value="ok"]', { timeout: 3000 }); // "Close score and go home"
    await page.waitForSelector("#view-home:not([hidden])", { timeout: 3000 });
  } catch {
    failures.push("Home didn't go home from Practice after opening a score from the Library");
    await page.goto("http://localhost:4319/");
  }

  await page.click('.home-card[data-go="convert"]');
  await page.click("#cv-tab-review");
  if (!(await page.textContent("#cv-rv-list li:first-child"))?.includes("Check")) failures.push("A flagged conversion had no Check badge in the Review list");
  await page.click(".cv-rv-open");
  await page.waitForSelector("#rv-xml svg", { timeout: 15000 });
  if (!(await page.isVisible("#rv-found")) || !(await page.textContent("#rv-found"))?.includes("116 slurs"))
    failures.push("The Review window didn't show what the converter found");
  await page.waitForTimeout(500); // let the PDF frame load and add its history entry
  await page.click("#rv-split"); // flags the first one, "Other Piece"
  if ((await page.getAttribute("#rv-split", "aria-pressed")) !== "true") failures.push("Flag for splitting didn't flag the PDF");
  if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/review-flagged.png` });
  await page.click("#rv-next").catch(() => {});
  await page.click("#rv-close");
  try {
    await page.waitForSelector("#cv-rv-list li:last-child:has-text('Other Piece')", { timeout: 2000 });
  } catch {
    failures.push("A PDF flagged for splitting didn't move to the bottom of the Review list");
  }
  if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/review-list.png` });
  try {
    await page.click("#cv-split-open:not([hidden])", { timeout: 2000 });
    await page.waitForSelector("#cv-split[open] #cv-split-list li:has-text('Other Piece')", { timeout: 2000 });
    if (process.env.E2E_SHOTS) await page.screenshot({ path: `${process.env.E2E_SHOTS}/split-list.png` });
    await page.click('#cv-split-list button:has-text("Done")');
    await page.waitForSelector("#cv-split-list li.done", { timeout: 2000 });
    if ((await page.textContent("#cv-split-title"))?.includes("(")) failures.push("A PDF marked done still counts as to split");
    await page.click("#cv-split-close");
  } catch {
    failures.push("The flagged PDF didn't show on the To split screen, or couldn't be marked done");
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
console.log("Home works from every screen and after a review; a score opened from the Library leaves Practice usable; Flag for splitting sorts last and reaches the To split screen.");
