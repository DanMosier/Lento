/** Tuner: listens to the (stand-in) microphone, stops, and plays reference tones. */
import { openScreen, test, expect } from "./fixtures";

test("starts and stops listening", async ({ page }) => {
  await openScreen(page, "tuner");
  await expect(page.locator("#tuner-readout")).toHaveText("Not listening");
  await page.click("#tuner-toggle");
  await expect(page.locator("#tuner-toggle")).toHaveText("Stop listening");
  await expect(page.locator("#tuner-readout")).not.toHaveText("Not listening");
  await expect(page.locator("#tuner-readout")).not.toContainText("Could not use the microphone");
  await page.click("#tuner-toggle");
  await expect(page.locator("#tuner-readout")).toHaveText("Not listening");
});

test("reference tone buttons respond", async ({ page }) => {
  await openScreen(page, "tuner");
  for (const note of ["C", "G", "D", "A"]) await page.locator(".tuner-refs button", { hasText: note }).click();
});

test("stops listening when you leave the Tuner", async ({ page }) => {
  await openScreen(page, "tuner");
  await page.click("#tuner-toggle");
  await expect(page.locator("#tuner-toggle")).toHaveText("Stop listening");
  await page.click("#home-btn");
  await page.click('.home-card[data-go="tuner"]');
  await expect(page.locator("#tuner-toggle")).toHaveText("Start listening");
});
