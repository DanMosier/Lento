/** Settings: changes are kept and reach the features that use them. */
import { goHome, openScreen, test, expect } from "./fixtures";

test("tuning (A =) set here is used by the Tuner", async ({ page }) => {
  await openScreen(page, "settings");
  await page.fill("#set-a4", "442");
  await page.press("#set-a4", "Enter");
  await page.locator("#set-a4").blur();
  await goHome(page);
  await openScreen(page, "tuner");
  await expect(page.locator("#tuner-a4")).toHaveValue("442");
});

test("settings are still there after reloading the app", async ({ page }) => {
  await openScreen(page, "settings");
  await page.locator("#set-sound").selectOption("synth");
  await page.locator("#set-room").uncheck();
  await page.reload();
  await openScreen(page, "settings");
  await expect(page.locator("#set-sound")).toHaveValue("synth");
  await expect(page.locator("#set-room")).not.toBeChecked();
});

test("headphone delay slider shows its value", async ({ page }) => {
  await openScreen(page, "settings");
  await page.locator("#set-delay").fill("100");
  await expect(page.locator("#set-delay-out")).toContainText("100");
});

test("About shows the version and the problems list", async ({ page }) => {
  await openScreen(page, "settings");
  await expect(page.locator("#set-version")).not.toBeEmpty();
  await expect(page.locator("#set-problems")).toContainText("Nothing so far"); // a fresh device has no problems
  await expect(page.locator("#set-clear-problems")).toBeHidden(); // so there's nothing to clear
});
