/**
 * Shared set-up for the browser tests in this folder.
 *
 * Every test gets a `page` with the app open on the home screen and a stand-in for the Google Drive library (so no
 * sign-in or network is needed). After every test, `noBlockers` runs: it fails the test if a window is open but
 * invisible, if the loading screen is stuck, or if the page threw an error. Those are the leftovers that make
 * buttons stop responding.
 *
 * Read docs/TESTING.md for how to run these and read the results.
 */
import { test as base, expect, type Page } from "@playwright/test";

// ---- test data ----

/** A tiny one-part score (four quarter notes on the C string). */
export const SOLO_XML = `<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0"><work><work-title>Test Piece</work-title></work><part-list><score-part id="P1"><part-name>Violoncello</part-name></score-part></part-list><part id="P1"><measure number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>F</sign><line>4</line></clef></attributes><note><pitch><step>C</step><octave>3</octave></pitch><duration>1</duration><type>quarter</type></note><note><pitch><step>D</step><octave>3</octave></pitch><duration>1</duration><type>quarter</type></note><note><pitch><step>E</step><octave>3</octave></pitch><duration>1</duration><type>quarter</type></note><note><pitch><step>F</step><octave>3</octave></pitch><duration>1</duration><type>quarter</type></note></measure><measure number="2"><note><pitch><step>G</step><octave>3</octave></pitch><duration>4</duration><type>whole</type></note></measure></part></score-partwise>`;

/** A two-part score, so Practice asks which part to practise. */
export const DUET_XML = SOLO_XML.replace("<work-title>Test Piece</work-title>", "<work-title>Duet</work-title>")
  .replace("</part-list>", `<score-part id="P2"><part-name>Piano</part-name></score-part></part-list>`)
  .replace(
    "</score-partwise>",
    `<part id="P2"><measure number="1"><attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes><note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note></measure><measure number="2"><note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note></measure></part></score-partwise>`,
  );

/** A small PDF with `pages` blank pages, each with its number written on it (for the PDF splitter). */
export function pdfBytes(pages = 3): Buffer {
  const objs: string[] = [];
  const kids = Array.from({ length: pages }, (_, i) => `${4 + i * 2} 0 R`).join(" ");
  objs.push("<< /Type /Catalog /Pages 2 0 R >>");
  objs.push(`<< /Type /Pages /Kids [${kids}] /Count ${pages} >>`);
  objs.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  for (let i = 0; i < pages; i++) {
    const text = `BT /F1 48 Tf 100 600 Td (Page ${i + 1}) Tj ET`;
    objs.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents ${5 + i * 2} 0 R >>`);
    objs.push(`<< /Length ${text.length} >>\nstream\n${text}\nendstream`);
  }
  let out = "%PDF-1.4\n";
  const offsets = objs.map((body, i) => {
    const at = out.length;
    out += `${i + 1} 0 obj\n${body}\nendobj\n`;
    return at;
  });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

/**
 * The stand-in library: one piece ready to practise, one PDF waiting for MusicXML, one whose conversion failed and
 * one converted score marked "Check". Titles sort so "Bach Suite" comes first.
 */
export const LIBRARY = {
  version: 1,
  generated: "2026-11-26T00:00:00Z",
  pieces: [
    { id: "bach_suite", title: "Bach Suite", composer: "Bach", genre: "Baroque", level: "Intermediate", tags: ["chords"], musicxml: true, files: [{ name: "bach_suite__x.pdf", kind: "pdf", variant: "x", musicxml: "bach_suite__x.musicxml" }] },
    { id: "elgar_salut", title: "Elgar Salut", composer: "Elgar", genre: "Romantic", level: "Beginner", files: [{ name: "elgar_salut__x.pdf", kind: "pdf", variant: "x" }] },
    { id: "faure_elegie", title: "Faure Elegie", composer: "Faure", files: [{ name: "faure_elegie__x.pdf", kind: "pdf", variant: "x", convert_failed: true, convert_error: "too faint" }] },
    { id: "saint_swan", title: "Saint-Saens Swan", composer: "Saint-Saens", musicxml: true, files: [{ name: "saint_swan__x.pdf", kind: "pdf", variant: "x", musicxml: "saint_swan__x.musicxml", quality: "REVIEW", quality_note: "left out 116 slurs and 2 octave lines (8va) that did not start or end properly" }] },
  ],
};

/** Replaces the Google Drive library with LIBRARY, keeping anything the app saves in memory for this test. */
export async function useFakeLibrary(page: Page): Promise<void> {
  await page.route("https://drive.example/**", (r) =>
    // like Drive's real PDF viewer, it adds a history entry inside the frame
    r.fulfill({ contentType: "text/html", body: '<p>PDF</p><script>history.pushState({}, "", location.href + "#2")</script>' }),
  );
  await page.addInitScript(() => localStorage.setItem("lento.library.folder", JSON.stringify("https://drive.google.com/drive/folders/e2etestfolder")));
  await page.goto("/");
  await page.evaluate(
    async ([index, xml]) => {
      const path = "/src/core/library/library.ts"; // served by the dev server
      const { DriveLibrary } = await import(/* @vite-ignore */ path);
      const saved = new Map<string, unknown>();
      const P = DriveLibrary.prototype as unknown as Record<string, unknown>;
      P.cachedIndex = P.loadIndex = async () => index;
      P.newerIndex = async () => null;
      P.pcStatus = async () => null;
      P.readRootJson = async (name: string) => saved.get(`root/${name}`) ?? null;
      P.writeRootJson = async (name: string, content: unknown) => void saved.set(`root/${name}`, content);
      P.readSidecar = async (id: string, name: string) => saved.get(`${id}/${name}`) ?? null;
      P.writeSidecar = async (id: string, name: string, content: unknown) => void saved.set(`${id}/${name}`, content);
      P.writeFixedScore = async () => {};
      P.requestConversion = async (items: unknown[]) => items.length;
      P.cancelConversion = async (names: string[]) => ({ removed: names, failed: [] });
      P.open = async (_piece: unknown, file: { kind: string }) =>
        file.kind === "pdf" ? { link: "https://drive.example/file/d/1/view", offline: false } : { data: new TextEncoder().encode(xml).buffer, offline: false };
    },
    [LIBRARY, SOLO_XML] as const,
  );
}

// ---- moving around ----

export const SCREENS = ["practice", "library", "convert", "tuner", "settings"] as const;

/** Opens a feature from the home screen. */
export async function openScreen(page: Page, screen: (typeof SCREENS)[number]): Promise<void> {
  await page.click(`.home-card[data-go="${screen}"]`);
  await expect(page.locator(`#view-${screen}`)).toBeVisible();
  // each feature's code loads the first time its screen opens; wait until it has, so its buttons are wired up
  await page.waitForFunction((s) => performance.getEntriesByName(`lento:entered-${s}`).length > 0, screen, { timeout: 20_000 });
}

/** Presses Home (and "Close score and go home" if Practice asks) and checks the home screen shows. */
export async function goHome(page: Page): Promise<void> {
  await page.click("#home-btn");
  const home = page.locator("#view-home");
  const leave = page.locator('#leave-dialog[open] button[value="ok"]');
  // either home shows, or Practice asks first
  await page
    .waitForFunction(() => !document.getElementById("view-home")!.hidden || document.querySelector("#leave-dialog[open]"), null, { timeout: 3000 })
    .catch(() => {});
  if (await leave.isVisible()) await leave.click();
  await expect(home, "Home should go to the home screen").toBeVisible({ timeout: 3000 });
}

/** Opens a MusicXML file in Practice the way a person would, with the Open score button's file picker. */
export async function openScoreFile(page: Page, xml: string, name = "test.musicxml"): Promise<void> {
  await page.setInputFiles("#score-file", { name, mimeType: "application/xml", buffer: Buffer.from(xml) });
}

/** Waits for the score to be drawn and the controls to show. */
export async function scoreReady(page: Page): Promise<void> {
  await page.waitForFunction(() => performance.getEntriesByName("lento:open-score").length > 0, null, { timeout: 20_000 });
  await expect(page.locator("#loading")).toBeHidden({ timeout: 20_000 });
  await expect(page.locator("#sheet svg").first()).toBeVisible();
}

// ---- the checks for things that block taps ----

export interface Blocked {
  control: string;
  coveredBy: string;
}

/**
 * The dead-button sweep. Finds every control a person could tap right now (buttons, tabs, menus, checkboxes,
 * sliders, text boxes, "Open score"-style labels, and expandable sections) and, for each, scrolls it into view and
 * asks the browser what is under its center. If that isn't the control itself, something is in the way: an
 * invisible window, the loading screen, a toast, a toolbar, or a page made inert by a modal window. Returns those.
 *
 * When a window (dialog) is open, only the controls inside it are checked, since it is meant to cover the page.
 */
export async function findBlockedControls(page: Page): Promise<Blocked[]> {
  return page.evaluate(async () => {
    const describe = (el: Element | null): string => {
      if (!el) return "nothing (outside the page)";
      // taps fall through to the page itself when an open window has made everything else inert
      if (el === document.documentElement || el === document.body) return "nothing: the page is blocked (usually by an open window)";
      const id = el.id ? `#${el.id}` : "";
      const cls = typeof el.className === "string" && el.className.trim() ? `.${el.className.trim().split(/\s+/).join(".")}` : "";
      const label = (el.getAttribute("aria-label") || el.getAttribute("title") || (el as HTMLElement).innerText || "").trim().replace(/\s+/g, " ").slice(0, 40);
      return `<${el.tagName.toLowerCase()}${id}${cls}>${label ? ` "${label}"` : ""}`;
    };
    const dialogs = [...document.querySelectorAll<HTMLDialogElement>("dialog[open]")];
    // a window that is open but can't be seen doesn't count: the page behind it is what the person sees and taps
    const seen = (d: Element) => d.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && d.getBoundingClientRect().width > 0;
    const modal = dialogs.filter((d) => d.matches(":modal") && seen(d)).at(-1);
    const scope: ParentNode = modal ?? document;
    const selector = [
      "button",
      "select",
      "summary",
      "input:not([type=hidden]):not([type=file])",
      "label[for]",
      '[role="tab"]',
      "a[href]",
    ].join(",");
    const controls = [...scope.querySelectorAll<HTMLElement>(selector)].filter((el) => {
      if ((el as HTMLButtonElement).disabled) return false;
      if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
      // a <label for> only counts when it is styled as a button (like "Open score")
      if (el.tagName === "LABEL" && !el.classList.contains("button")) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    });
    const out: { control: string; coveredBy: string }[] = [];
    for (const el of controls) {
      el.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
      await new Promise((r) => requestAnimationFrame(() => r(null)));
      const r = el.getBoundingClientRect();
      const x = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1);
      const y = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
      // anything partly off-screen after scrolling: test the part that is on screen
      const hit = document.elementFromPoint(x, y);
      const ok = !!hit && (hit === el || el.contains(hit) || (el.tagName === "LABEL" && (el as HTMLLabelElement).control === hit) || (hit as HTMLLabelElement).control === el || hit.closest("label")?.contains(el));
      if (!ok) out.push({ control: describe(el), coveredBy: describe(hit) });
    }
    window.scrollTo(0, 0);
    return out;
  });
}

/** Problems that leave the app looking fine but unresponsive. Empty when all is well. */
export async function findLeftovers(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const problems: string[] = [];
    for (const d of document.querySelectorAll<HTMLDialogElement>("dialog[open]")) {
      const r = d.getBoundingClientRect();
      const seen = d.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true }) && r.width > 0 && r.height > 0;
      if (!seen) problems.push(`The window #${d.id} is open but invisible${d.matches(":modal") ? ", so it blocks every tap on the page" : ""}`);
    }
    const loading = document.getElementById("loading");
    if (loading && loading.checkVisibility() && !document.querySelector("#view-practice:not([hidden])"))
      problems.push("The loading screen is showing on a screen that isn't Practice");
    for (const el of document.querySelectorAll<HTMLElement>("[inert]")) problems.push(`<${el.tagName.toLowerCase()}#${el.id}> is inert, so nothing in it can be tapped`);
    return problems;
  });
}

/** Runs both checks and fails the test (without stopping it) with a plain description of what's wrong. */
export async function expectNothingBlocking(page: Page, where: string): Promise<void> {
  await test.step(`Nothing blocks the buttons: ${where}`, async () => {
    // let a loading screen finish first
    await expect(page.locator("#loading"), `${where}: the loading screen didn't go away`).toBeHidden({ timeout: 20_000 });
    const leftovers = await findLeftovers(page);
    expect.soft(leftovers, `${where}: something left behind blocks the page`).toEqual([]);
    const blocked = await findBlockedControls(page);
    expect.soft(blocked, `${where}: these controls can't be tapped because something covers them`).toEqual([]);
  });
}

// ---- the test fixture ----

export const test = base.extend<{ errors: string[] }>({
  errors: async ({}, use) => use([]),
  page: async ({ page, errors }, use) => {
    page.on("pageerror", (e) => errors.push(e.message));
    await useFakeLibrary(page);
    await use(page);
    // after every test: the leftovers check and no uncaught errors
    const leftovers = await findLeftovers(page).catch(() => []);
    expect.soft(leftovers, "At the end of the test, something left behind blocks the page").toEqual([]);
    expect.soft(errors, "The page threw errors").toEqual([]);
  },
});

export { expect };
