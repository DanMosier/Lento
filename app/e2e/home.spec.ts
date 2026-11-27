/**
 * Getting around: the Home button returns to the home screen from every feature, the phone's Back button does too,
 * and a score opened from the Library leaves Practice usable.
 */
import { SCREENS, goHome, openScreen, scoreReady, test, expect } from "./fixtures";

for (const screen of SCREENS)
  test(`Home goes home from ${screen}`, async ({ page }) => {
    await openScreen(page, screen);
    await goHome(page);
  });

test("the Back button goes home", async ({ page }) => {
  await openScreen(page, "settings");
  await page.goBack();
  await expect(page.locator("#view-home")).toBeVisible();
});

test("a score opened from the Library leaves Practice usable (PR #47)", async ({ page }) => {
  await openScreen(page, "library");
  await page.locator(".lib-body .lib-row", { hasText: "Bach Suite" }).click();
  await page.locator('#lib-detail button:has-text("Practice")').click();
  await scoreReady(page);
  await expect(page.locator("dialog[open]"), "no window should stay open behind Practice").toHaveCount(0);
  await page.click("#play");
  await expect(page.locator("#play")).toHaveText("Stop");
  await page.click("#play");
  await expect(page.locator("#play")).toHaveText("Play");
  await goHome(page);
});

test("going home with a score open asks first, and Stay keeps the score", async ({ page }) => {
  await openScreen(page, "library");
  await page.locator(".lib-body .lib-row", { hasText: "Bach Suite" }).click();
  await page.locator('#lib-detail button:has-text("Practice")').click();
  await scoreReady(page);
  await page.click("#home-btn");
  await page.click('#leave-dialog button[value="cancel"]'); // Stay
  await expect(page.locator("#view-practice")).toBeVisible();
  await expect(page.locator("#sheet svg").first()).toBeVisible();
  await goHome(page);
});
