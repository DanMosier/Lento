/** Convert PDF: choose PDFs and queue them, the Review window (play, fix, flag for splitting), the To split list. */
import { openScreen, test, expect } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await openScreen(page, "convert");
  await expect(page.locator("#cv-todo li").first()).toBeVisible();
});

test("lists PDFs without MusicXML, and queues the chosen ones", async ({ page }) => {
  await expect(page.locator("#cv-todo")).toContainText("Elgar Salut");
  await expect(page.locator("#cv-failed-box")).toContainText("Faure Elegie");
  await expect(page.locator("#cv-go")).toBeDisabled();
  await page.click("#cv-all");
  await expect(page.locator("#cv-go")).toBeEnabled();
  await page.click("#cv-go");
  await expect(page.locator("#cv-status")).not.toBeEmpty();
});

test("the Review window plays the score, then stops", async ({ page }) => {
  await page.click("#cv-tab-review");
  await page.click(".cv-rv-open");
  await expect(page.locator("#rv-xml svg")).toBeVisible({ timeout: 20_000 });
  await page.click("#rv-play");
  await expect(page.locator("#rv-play")).toHaveAttribute("aria-pressed", "true", { timeout: 15_000 });
  await page.click("#rv-play");
  await expect(page.locator("#rv-play")).toHaveAttribute("aria-pressed", "false");
  await page.click("#rv-close");
  await expect(page.locator("#rv")).toBeHidden();
});

test("PDF / Both / MusicXML switch what the Review window shows", async ({ page }) => {
  await page.click("#cv-tab-review");
  await page.click(".cv-rv-open");
  for (const show of ["pdf", "xml", "both"]) {
    await page.click(`#rv [data-show="${show}"]`);
    await expect(page.locator("#rv-panes")).toHaveAttribute("data-show", show);
  }
  await page.click("#rv-close");
});

test("a fix in the Review window can be undone", async ({ page }) => {
  await page.click("#cv-tab-review");
  await page.click(".cv-rv-open");
  await expect(page.locator("#rv-xml svg")).toBeVisible({ timeout: 20_000 });
  await page.click("#rv-fix summary");
  await page.click("#rv-key-go");
  await expect(page.locator("#rv-undo")).toBeEnabled();
  await page.click("#rv-undo");
  await expect(page.locator("#rv-undo")).toBeDisabled();
  await page.click("#rv-close");
});

test("Approve takes a score off the To review list", async ({ page }) => {
  await page.click("#cv-tab-review");
  const before = await page.locator("#cv-rv-list li").count();
  await page.click(".cv-rv-open");
  await page.click("#rv-approve");
  await page.locator("#rv-close").click({ timeout: 2000 }).catch(() => {}); // approving the last one may close it
  await expect(page.locator("#rv")).toBeHidden();
  await expect(page.locator("#cv-rv-list li .cv-rv-open")).toHaveCount(before - 1);
});

test("Flag for splitting moves a PDF to the bottom and onto the To split list (PR #46, #51)", async ({ page }) => {
  await page.click("#cv-tab-review");
  await page.click(".cv-rv-open");
  await page.waitForTimeout(500); // let the PDF frame load and add its history entry
  const name = (await page.locator("#rv-name").textContent())!;
  await page.click("#rv-split");
  await expect(page.locator("#rv-split")).toHaveAttribute("aria-pressed", "true");
  await page.click("#rv-close");
  await expect(page.locator("#cv-rv-list li").last()).toContainText(name);
  await page.click("#cv-split-open");
  await expect(page.locator("#cv-split-list")).toContainText(name);
  await page.click('#cv-split-list button:has-text("Done")');
  await expect(page.locator("#cv-split-list li.done")).toHaveCount(1);
  await expect(page.locator("#cv-split-title")).not.toContainText("(");
  await page.click("#cv-split-close");
});
