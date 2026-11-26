/** Practice: open a score, choose parts, play, change tempo, transpose, marks, hide controls, Wait mode. */
import { DUET_XML, SOLO_XML, openScoreFile, openScreen, scoreReady, test, expect } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await openScreen(page, "practice");
});

test("opens a score and plays it", async ({ page }) => {
  await openScoreFile(page, SOLO_XML);
  await scoreReady(page);
  await expect(page.locator("#title")).toContainText("Test Piece");
  await page.click("#play");
  await expect(page.locator("#play")).toHaveText("Stop");
  await page.click("#play");
  await expect(page.locator("#play")).toHaveText("Play");
});

test("asks which part to practise in a score with several parts", async ({ page }) => {
  await openScoreFile(page, DUET_XML, "duet.musicxml");
  await expect(page.locator("#parts-dialog")).toBeVisible();
  await page.click("#parts-all");
  await page.click('#parts-dialog button[value="ok"]');
  await scoreReady(page);
  await expect(page.locator("#parts-btn")).toBeVisible();
  await expect(page.locator("#accomp-label")).toBeVisible(); // "Play other shown parts"
});

test("tempo slider changes the tempo shown", async ({ page }) => {
  await openScoreFile(page, SOLO_XML);
  await scoreReady(page);
  await page.locator("#tempo").fill("50");
  await expect(page.locator("#tempo-out")).toContainText("50%");
});

test("transposing and changing clef redraw the score", async ({ page }) => {
  await openScoreFile(page, SOLO_XML);
  await scoreReady(page);
  const before = await page.locator("#sheet").innerHTML();
  await page.locator("#transpose").selectOption({ index: 0 });
  await expect.poll(() => page.locator("#sheet").innerHTML(), { timeout: 10_000 }).not.toBe(before);
  const clefs = await page.locator("#clef option").count();
  if (clefs > 1) await page.locator("#clef").selectOption({ index: clefs - 1 });
  await expect(page.locator("#loading")).toBeHidden({ timeout: 10_000 });
});

test("Marks mode opens and closes", async ({ page }) => {
  await openScoreFile(page, SOLO_XML);
  await scoreReady(page);
  await page.click("#marks-btn");
  await expect(page.locator("#marks-bar")).toBeVisible();
  await page.click('#marks-bar [data-kind="finger"][data-value="1"]');
  await page.click("#marks-done");
  await expect(page.locator("#marks-bar")).toBeHidden();
});

test("Hide controls shows the mini bar, and Show controls brings them back", async ({ page }) => {
  await openScoreFile(page, SOLO_XML);
  await scoreReady(page);
  await page.click("#focus-btn");
  await expect(page.locator("#mini-bar")).toBeVisible();
  await expect(page.locator("#controls")).toBeHidden();
  await page.click("#mini-play");
  await expect(page.locator("#mini-play")).toHaveText("Stop");
  await page.click("#mini-play");
  await page.click("#mini-show");
  await expect(page.locator("#controls")).toBeVisible();
});

test("Wait mode starts and stops", async ({ page }) => {
  await openScoreFile(page, SOLO_XML);
  await scoreReady(page);
  await page.click("#wait");
  await expect(page.locator("#wait-panel")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#wait-note")).not.toBeEmpty();
  await page.click("#wait-skip");
  await page.click("#wait-stop");
  await expect(page.locator("#wait-panel")).toBeHidden();
});

test("the speed trainer starts and stops", async ({ page }) => {
  await openScoreFile(page, SOLO_XML);
  await scoreReady(page);
  await page.locator("#trainer summary").click();
  await page.click("#tr-go");
  await expect(page.locator("#tr-go")).not.toHaveText("Start trainer");
  await page.click("#tr-go");
  await expect(page.locator("#tr-go")).toHaveText("Start trainer");
});

test("tapping a note plays from it", async ({ page }) => {
  await openScoreFile(page, SOLO_XML);
  await scoreReady(page);
  await expect(page.locator("#tap-play")).toBeChecked();
  const head = page.locator("#sheet svg g.vf-notehead").last();
  await head.scrollIntoViewIfNeeded();
  const box = (await head.boundingBox())!;
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.locator("#play")).toHaveText("Stop", { timeout: 5000 });
  await page.click("#play");
});
