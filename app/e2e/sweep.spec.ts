/**
 * The dead-button sweep: visits every screen, and every window and panel that can open on it, and checks that each
 * control a person can see can really be tapped (nothing invisible on top of it, nothing left open behind it).
 * Runs at phone, phone landscape, tablet and desktop size.
 */
import { DUET_XML, SOLO_XML, pdfBytes, expectNothingBlocking, goHome, openScoreFile, openScreen, scoreReady, test, expect } from "./fixtures";

test("Home screen", async ({ page }) => {
  await expectNothingBlocking(page, "Home");
});

test("Practice", async ({ page }) => {
  await openScreen(page, "practice");
  await expectNothingBlocking(page, "Practice with no score");

  await openScoreFile(page, DUET_XML, "duet.musicxml");
  await expect(page.locator("#parts-dialog")).toBeVisible();
  await expectNothingBlocking(page, "Practice: Choose parts window");
  await page.click('#parts-dialog button[value="ok"]');
  await scoreReady(page);
  await expectNothingBlocking(page, "Practice with a score open");

  for (const more of ["Speed trainer", "Settings"]) {
    await page.locator("#controls summary", { hasText: more }).click();
    await expectNothingBlocking(page, `Practice: ${more} opened`);
  }
  await page.click("#av-measure");
  await expectNothingBlocking(page, "Practice: headphone delay tap test");
  await page.click("#av-close");

  await page.click("#marks-btn");
  await expect(page.locator("#marks-bar")).toBeVisible();
  await expectNothingBlocking(page, "Practice: Marks");
  await page.click("#marks-done");

  await page.click("#focus-btn");
  await expect(page.locator("#mini-bar")).toBeVisible();
  await expectNothingBlocking(page, "Practice: Hide controls (mini bar)");
  await page.click("#mini-show");

  await page.click("#parts-btn");
  await expectNothingBlocking(page, "Practice: Parts window reopened");
  await page.click('#parts-dialog button[value="cancel"]');

  await page.click("#home-btn");
  await expect(page.locator("#leave-dialog")).toBeVisible();
  await expectNothingBlocking(page, "Practice: Close this score? window");
  await page.click('#leave-dialog button[value="cancel"]');
  await expectNothingBlocking(page, "Practice after choosing Stay");
});

test("Library", async ({ page }) => {
  await openScreen(page, "library");
  await expect(page.locator(".lib-body .lib-row").first()).toBeVisible();
  await expectNothingBlocking(page, "Library");

  await page.locator(".lib-body .lib-row", { hasText: "Bach Suite" }).click();
  await expect(page.locator("#lib-detail")).toBeVisible();
  await expectNothingBlocking(page, "Library: a piece's window");
  await page.click("#lib-detail-close");

  await page.click("#lib-tab-fav");
  await expectNothingBlocking(page, "Library: Favorites tab");
  await page.click("#lib-tab-all");

  await page.click("#lib-sets-open");
  await expect(page.locator("#lib-sets")).toBeVisible();
  await expectNothingBlocking(page, "Library: Setlists window");
  await page.fill('#lib-sets input[aria-label="New setlist name"]', "Recital");
  await page.click('#lib-sets button:has-text("Create")');
  await expect(page.locator("#lib-sets-title")).toHaveText("Recital");
  await expectNothingBlocking(page, "Library: one setlist");
  await page.click("#lib-sets-close");
  await expectNothingBlocking(page, "Library after closing Setlists");
});

test("Convert PDF", async ({ page }) => {
  await openScreen(page, "convert");
  await expect(page.locator("#cv-todo li").first()).toBeVisible();
  await expectNothingBlocking(page, "Convert PDF: Choose PDFs");
  await page.click("#cv-tab-queue");
  await expectNothingBlocking(page, "Convert PDF: Queue");
  await page.click("#cv-tab-review");
  await expectNothingBlocking(page, "Convert PDF: Review");

  await page.click(".cv-rv-open");
  await expect(page.locator("#rv")).toBeVisible();
  await expect(page.locator("#rv-xml svg")).toBeVisible({ timeout: 20_000 });
  await expectNothingBlocking(page, "Convert PDF: review window");
  await page.click("#rv-fix summary");
  await expectNothingBlocking(page, "Convert PDF: review window with Fix opened");
  for (const show of ["pdf", "xml", "both"]) await page.click(`#rv [data-show="${show}"]`);
  await page.click("#rv-split");
  await page.click("#rv-close");

  await page.click("#cv-split-open");
  await expect(page.locator("#cv-split")).toBeVisible();
  await expectNothingBlocking(page, "Convert PDF: To split window");
  await page.setInputFiles("#cv-split-file", { name: "two-pieces.pdf", mimeType: "application/pdf", buffer: pdfBytes(3) });
  await expect(page.locator("#sp .sp-page").first()).toBeVisible({ timeout: 20_000 });
  await expectNothingBlocking(page, "Convert PDF: PDF splitter");
  await page.click("#sp-close");
  await expect(page.locator("#sp")).toBeHidden();
  await page.click("#cv-split-close");
  await expectNothingBlocking(page, "Convert PDF after closing To split");
});

test("Tuner", async ({ page }) => {
  await openScreen(page, "tuner");
  await expectNothingBlocking(page, "Tuner");
  await page.click("#tuner-toggle");
  await expect(page.locator("#tuner-toggle")).toHaveAttribute("aria-pressed", "true");
  await expectNothingBlocking(page, "Tuner while listening");
  await page.click("#tuner-toggle");
});

test("Settings", async ({ page }) => {
  await openScreen(page, "settings");
  await page.click("#view-settings details.advanced summary");
  await expectNothingBlocking(page, "Settings");
  for (const [sound, box] of [["soundfont", "#set-sf-box"], ["midi", "#set-midi-box"]]) {
    await page.locator("#set-sound").selectOption(sound);
    await expect(page.locator(box)).toBeVisible();
    await expectNothingBlocking(page, `Settings: playback sound "${sound}"`);
  }
});

test("Every screen after a trip through all the others", async ({ page }) => {
  // windows opened on one screen must not linger, unseen, over the next
  await openScreen(page, "library");
  await page.locator(".lib-body .lib-row").first().click();
  await expect(page.locator("#lib-detail")).toBeVisible();
  await page.locator('#lib-detail button:has-text("Practice")').click(); // opens the score in Practice
  await scoreReady(page);
  await goHome(page);
  await openScreen(page, "convert");
  await page.click("#cv-tab-review");
  await page.click(".cv-rv-open");
  await expect(page.locator("#rv-xml svg")).toBeVisible({ timeout: 20_000 });
  await page.click("#rv-close");
  await goHome(page);
  await openScreen(page, "practice");
  await openScoreFile(page, SOLO_XML);
  await scoreReady(page);
  for (const screen of ["practice", "library", "convert", "tuner", "settings"] as const) {
    await goHome(page);
    await openScreen(page, screen);
    await expectNothingBlocking(page, `${screen} after visiting the others`);
  }
});
