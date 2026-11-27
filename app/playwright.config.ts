/**
 * Browser tests (e2e/): each test drives the real app in Chromium the way a person would, at four screen sizes.
 *
 *   npm run e2e            run them all (prints a summary)
 *   npm run e2e:watch      open the visual runner: watch each test click through the app, step by step
 *   npm run e2e:report     open the report of the last run
 *
 * Read docs/TESTING.md for a walk-through.
 */
import { defineConfig, devices } from "@playwright/test";

const PORT = 4319;

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 5_000 },
  fullyParallel: true,
  workers: process.env.CI ? 2 : undefined,
  retries: 0, // a flaky GUI test is a bug to fix, not to hide
  // the HTML report is written after every run; `npm run e2e:report` opens it
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }], ["github"]] : [["list"], ["html", { open: "never" }]],
  outputDir: "test-results",
  use: {
    baseURL: `http://localhost:${PORT}`,
    actionTimeout: 5_000, // a tap that can't land in 5 s is a dead button: fail with what was in the way
    screenshot: "only-on-failure",
    trace: "retain-on-failure", // a step-by-step replay of every failed test, in the report
    video: "off",
    launchOptions: {
      ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
      // a stand-in microphone that plays a beep, and no permission pop-ups, for the Tuner and Wait mode
      args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
    },
  },
  projects: [
    { name: "phone", use: { ...devices["Pixel 7"] } },
    { name: "phone-landscape", use: { ...devices["Pixel 7 landscape"] } },
    { name: "tablet", use: { ...devices["Galaxy Tab S9"] } },
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 800 } } },
  ],
  webServer: {
    command: `npx vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
