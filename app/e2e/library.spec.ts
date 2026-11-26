/** Library: search, filters, a piece's window, favorites, setlists. */
import { openScreen, test, expect } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await openScreen(page, "library");
  await expect(page.locator(".lib-body .lib-row").first()).toBeVisible();
});

test("lists every piece, and search narrows the list", async ({ page }) => {
  await expect(page.locator(".lib-body .lib-row")).toHaveCount(4);
  await page.fill("#lib-search", "elgar");
  await expect(page.locator(".lib-body .lib-row")).toHaveCount(1);
  await expect(page.locator(".lib-body .lib-row")).toContainText("Elgar Salut");
});

test("the MusicXML filter shows only pieces ready to practise", async ({ page }) => {
  await page.locator("#lib-xml").selectOption("yes");
  await expect(page.locator(".lib-body .lib-row")).toHaveCount(2);
  await page.click("#lib-clear");
  await expect(page.locator(".lib-body .lib-row")).toHaveCount(4);
});

test("a piece's window opens and closes (✕, and a tap outside it)", async ({ page }) => {
  await page.locator(".lib-body .lib-row", { hasText: "Elgar Salut" }).click();
  await expect(page.locator("#lib-detail")).toBeVisible();
  await expect(page.locator("#lib-detail")).toContainText("Make MusicXML");
  await page.click("#lib-detail-close");
  await expect(page.locator("#lib-detail")).toBeHidden();
  await page.locator(".lib-body .lib-row", { hasText: "Elgar Salut" }).click();
  await page.mouse.click(2, 2); // the backdrop
  await expect(page.locator("#lib-detail")).toBeHidden();
});

test("a piece can be added to Favorites and shows on that tab", async ({ page }) => {
  await page.locator(".lib-body .lib-row", { hasText: "Bach Suite" }).click();
  await page.click("#lib-detail .lib-fav-btn");
  await expect(page.locator("#lib-detail .lib-fav-btn")).toHaveAttribute("aria-pressed", "true");
  await page.click("#lib-detail-close");
  await expect(page.locator("#lib-fav-count")).toHaveText("1");
  await page.click("#lib-tab-fav");
  await expect(page.locator(".lib-body .lib-row")).toHaveCount(1);
  await expect(page.locator(".lib-body .lib-row")).toContainText("Bach Suite");
});

test("setlists: make one, add a piece, reorder, delete", async ({ page }) => {
  await page.click("#lib-sets-open");
  await page.fill('#lib-sets input[aria-label="New setlist name"]', "Recital");
  await page.click('#lib-sets button:has-text("Create")');
  await expect(page.locator("#lib-sets-title")).toHaveText("Recital");
  for (const q of ["bach", "swan"]) {
    await page.fill('#lib-sets input[aria-label="Search for a piece to add"]', q);
    await page.locator("#lib-sets .sets-found button").first().click();
  }
  await expect(page.locator("#lib-sets .sets-pieces li")).toHaveCount(2);
  await page.locator('#lib-sets .sets-pieces li').nth(1).locator('button[aria-label="Move up"]').click();
  await expect(page.locator("#lib-sets .sets-pieces li").first()).toContainText("Saint-Saens Swan");
  await page.click("#lib-sets-back");
  await expect(page.locator("#lib-sets .sets-item")).toContainText("Recital");
  await page.locator("#lib-sets .sets-item").click();
  await page.locator("#lib-sets .sets-manage summary").click();
  await page.click('#lib-sets button:has-text("Delete setlist")');
  await page.click('#lib-sets button:has-text("Tap again to delete")');
  await expect(page.locator("#lib-sets .sets-item")).toHaveCount(0);
  await page.click("#lib-sets-close");
});

test("a piece can be added to a setlist from its window", async ({ page }) => {
  await page.locator(".lib-body .lib-row", { hasText: "Bach Suite" }).click();
  await page.locator("#lib-detail .lib-add-set").selectOption("+");
  await page.fill('#lib-detail input[aria-label="New setlist name"]', "Warm-ups");
  await page.click('#lib-detail .lib-new-set button:has-text("Create")');
  await page.click("#lib-detail-close");
  await page.click("#lib-sets-open");
  await expect(page.locator("#lib-sets .sets-item")).toContainText("Warm-ups");
  await page.click("#lib-sets-close");
});
