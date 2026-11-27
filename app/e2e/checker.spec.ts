/**
 * Tests for the tests: breaks the page on purpose in the ways that have made buttons go dead before, and checks the
 * sweep notices. If one of these fails, the sweep has stopped catching that kind of bug.
 */
import { findBlockedControls, findLeftovers, openScreen, test, expect } from "./fixtures";

test.describe.configure({ mode: "parallel" });

test("catches an invisible layer over the page", async ({ page }) => {
  await page.evaluate(() => {
    const veil = document.createElement("div");
    veil.style.cssText = "position:fixed;inset:0;opacity:0;z-index:99";
    document.body.append(veil);
  });
  const blocked = await findBlockedControls(page);
  expect(blocked.length).toBeGreaterThan(0);
  expect(blocked[0].coveredBy).toContain("<div");
  await page.evaluate(() => document.body.lastElementChild!.remove());
});

test("catches a window left open, unseen, on a hidden screen (the Library bug fixed in PR #47)", async ({ page }) => {
  await page.evaluate(() => (document.getElementById("lib-detail") as HTMLDialogElement).showModal()); // Library's screen is hidden
  expect(await findLeftovers(page)).toEqual([expect.stringContaining("#lib-detail is open but invisible")]);
  const blocked = await findBlockedControls(page);
  expect(blocked.map((b) => b.control).join()).toContain("#home-btn"); // every button on the page is dead, Home too
  await page.evaluate(() => (document.getElementById("lib-detail") as HTMLDialogElement).close());
});

test("catches a loading screen stuck on another screen", async ({ page }) => {
  await openScreen(page, "library");
  await page.evaluate(() => {
    const l = document.getElementById("loading")!;
    document.body.append(l); // as if a bug moved it out of Practice
    l.hidden = false;
  });
  expect(await findLeftovers(page)).toEqual([expect.stringContaining("loading screen")]);
  expect((await findBlockedControls(page)).length).toBeGreaterThan(0);
  await page.evaluate(() => (document.getElementById("loading")!.hidden = true));
});

test("catches a toolbar that covers buttons", async ({ page }) => {
  await page.evaluate(() => {
    const bar = document.createElement("div");
    bar.style.cssText = "position:fixed;left:0;right:0;top:0;height:60px;background:transparent;z-index:99";
    document.body.append(bar);
  });
  const blocked = await findBlockedControls(page);
  expect(blocked.map((b) => b.control).join()).toContain("#home-btn");
  await page.evaluate(() => document.body.lastElementChild!.remove());
});
