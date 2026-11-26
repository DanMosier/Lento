# Testing Lento

This guide covers what Lento's tests check, how to run them on your PC, and how to read the results. It also says
what to look at when something fails.

## The short version

From `D:\Coding\Lento` in PowerShell:

```powershell
.\run-tests.ps1              # everything (about 5 to 10 minutes)
.\run-tests.ps1 gui-phone    # just the browser tests at phone size (about a minute)
.\run-tests.ps1 gui-watch    # watch the browser tests click through the app
.\run-tests.ps1 report       # open the report of the last browser-test run
```

Each run ends with a summary like this:

```
=== Summary ===
  PASS  Unit tests (app logic)
  PASS  Python tests (converter, library, analyzer)
  FAIL  GUI tests (phone, phone landscape, tablet, desktop)
  PASS  Speed budgets
```

GitHub runs the same tests on every pull request (see [On GitHub](#on-github)), so you don't have to run them
yourself before merging. Run them when you want to see for yourself, or to check something on your own machine.

**First time only:** the script installs what it needs by itself: the app's packages, a copy of Chromium for the
browser tests, and pytest in `.venv`. You need [Node.js](https://nodejs.org) (the LTS version) installed. If
PowerShell refuses to run the script, use
`powershell -ExecutionPolicy Bypass -File .\run-tests.ps1` instead.

## The four kinds of test

| Kind | What it checks | Where it lives | How long |
| --- | --- | --- | --- |
| **Unit tests** | The app's logic on its own, without a screen: note matching, pitch detection, transposing, setlists, the review fixes and so on. | `app/test/*.test.ts` (run by Vitest) | seconds |
| **Python tests** | The PDF converter, the library tools, the PC watcher and the Python practice analyzer. | `tests/` (run by pytest) | about a minute |
| **GUI tests** | The real app in a real browser, used the way a person would: tapping buttons, opening windows, opening scores. Each test runs at four screen sizes: phone, phone on its side, tablet and desktop. | `app/e2e/*.spec.ts` (run by Playwright) | a few minutes |
| **Speed budgets** | That the app stays fast on a phone: startup, opening scores, starting playback and more, with the CPU slowed 4x. Each timing has a limit in `app/perf/budgets.json`. | `app/perf/` | a few minutes |

### The GUI tests, file by file

| File | What it checks |
| --- | --- |
| `sweep.spec.ts` | **The dead-button sweep** (see below). It visits every screen and every window that can open on it. |
| `home.spec.ts` | The Home button works from every screen, and so does the phone's Back button. Going home with a score open asks first. A score opened from the Library leaves Practice usable (the PR #47 bug). |
| `practice.spec.ts` | Opening a score, choosing parts, Play and Stop, the tempo slider, transpose and clef, Marks, Hide controls with the mini bar, Wait mode and the speed trainer. |
| `library.spec.ts` | Search, filters, a piece's window, Favorites, and making, filling, reordering and deleting setlists. |
| `convert.spec.ts` | Queuing PDFs, the Review window (Play, PDF / Both / MusicXML, a fix and Undo, Approve), and Flag for splitting with the To split list. |
| `tuner.spec.ts` | Listening starts and stops (the test browser has a pretend microphone that plays a beep), the reference tones, and that the tuner stops listening when you leave it. |
| `settings.spec.ts` | Settings are kept after a reload and reach the features that use them. The About section works. |
| `checker.spec.ts` | Tests for the sweep itself. It breaks the page on purpose (an invisible layer, a hidden window left open, a stuck loading screen) and checks the sweep notices each one. |
| `fixtures.ts` | Not a test. It's the shared setup: the pretend library and the helpers the tests use. |

The GUI tests never touch your real Google Drive. They swap the library for a pretend one with four pieces:
*Bach Suite* (ready to practise), *Elgar Salut* (PDF only), *Faure Elegie* (its conversion failed) and
*Saint-Saens Swan* (converted, marked "Check").

### The dead-button sweep

This is the check for "the buttons stopped working". On each screen, and with each window open, it:

1. finds every control you could tap right now: buttons, tabs, menus, checkboxes, sliders, text boxes and
   expandable sections;
2. scrolls each one into view and asks the browser *what is under the middle of it*;
3. fails if the answer isn't the control itself, and says what was on top of it.

It also fails if a window is open but invisible, if the loading screen is stuck, or if part of the page has been
switched off (made "inert"). Those are the leftovers behind bugs like the PR #47 one. The leftover check also runs
by itself at the end of **every** GUI test, not only the sweep.

When a window (such as a piece's window in the Library) is open, it's meant to cover the page, so the sweep only
checks the controls inside that window.

## Reading the results

### When everything passes

```
Running 184 tests using 4 workers
  ✓   1 [phone] › e2e/sweep.spec.ts:8:1 › Home screen (872ms)
  ✓   2 [phone] › e2e/library.spec.ts:16:1 › lists every piece, and search narrows the list (1.4s)
  ...
  184 passed (1.7m)
```

Each line names the screen size in brackets, the file, the line the test starts on, and the test's name.

### When something fails

There are three ways to see what went wrong, from quickest to most detailed.

**1. The message in PowerShell.** It says what was expected and what happened. Here is what the sweep prints when
a hidden window blocks the page (this is the PR #47 bug, put back on purpose):

```
✘ [phone] › e2e/sweep.spec.ts › Library

Error: Library: something left behind blocks the page
+   "The window #lib-detail is open but invisible, so it blocks every tap on the page",

Error: Library: these controls can't be tapped because something covers them
+   Object {
+     "control": "<button#home-btn.home-btn> \"Home\"",
+     "coveredBy": "nothing: the page is blocked (usually by an open window)",
+   },
+   Object {
+     "control": "<button.home-card> \"Practice Play along slowly, loop passage\"",
+     ...
```

Read it as: on the Library step, the window `#lib-detail` is open but you can't see it, so **Home** and every
other button are dead. `control` is the button that can't be tapped. `coveredBy` is what's on top of it.

A test that taps a button which can't be tapped fails after 5 seconds with a message like this:

```
TimeoutError: page.click: Timeout 5000ms exceeded.
  - <dialog open id="lib-detail"> from <div id="view-library"> subtree intercepts pointer events
```

"Intercepts pointer events" means *something else got the tap*. The message names what it was.

A plain check that didn't come true looks like this:

```
Error: expect(locator).toHaveText(expected) failed
Locator:  locator('#play')
Expected: "Stop"
Received: "Play"
```

That reads as: after pressing Play, the button should have changed to "Stop", but it still said "Play".

**2. The HTML report** (`.\run-tests.ps1 report`, which opens it in your browser). It's written after every GUI
run. It lists every test, and you can click a failed one to see:

- the **error message**, as above;
- a **screenshot** of the app at the moment it failed. A hidden blocker often shows up here as a greyed-out page
  or a window in an odd place;
- the **steps** the test took. Steps named "Nothing blocks the buttons: …" are the sweep's checks.

**3. The trace (a replay).** In the report, click **Trace** under a failed test. The trace viewer shows the
whole test as a timeline. Click any step to see the page at that moment, before and after the tap, with a red dot
where the tap landed. The **Console** tab shows the app's own errors. This is the best way to see *why*
something happened.

### Watching tests run

`.\run-tests.ps1 gui-watch` opens Playwright's test window:

- Pick a test on the left and press ▶ to run it. The middle shows the app as the test drives it.
- Click any step afterwards to see the page at that moment.
- Tick **Watch** (the eye icon) to re-run a test whenever its file changes.
- The screen-size names (phone, tablet and so on) are under **Projects**, at the top left.

This is the easiest way to get a feel for what each test does.

### Running one test, or one screen size

From the `app` folder:

```powershell
cd app
npx playwright test library                      # every test in library.spec.ts
npx playwright test -g "Favorites"               # tests whose name contains "Favorites"
npx playwright test --project=desktop            # only at desktop size
npx playwright test sweep --headed --project=phone   # show the browser window while it runs
npx vitest run test/lists.test.ts                # one unit test file
```

And for Python, from `D:\Coding\Lento`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\library -v        # one folder, each test named
.\.venv\Scripts\python.exe -m pytest -k split -v             # tests with "split" in the name
```

## On GitHub

Every pull request runs:

| Check | Runs |
| --- | --- |
| **App / test** | unit tests and a build |
| **App / perf** | the speed budgets |
| **App / e2e** | the GUI tests at all four sizes |
| **Python / pytest** | the Python tests (without the GPU-only homr tests) |

They appear at the bottom of the pull request. A red ✗ means one failed: click **Details** to see the same output as
in PowerShell. For the GUI tests, the run's **Summary** page has a download called **gui-test-report**. Unzip it and
open `index.html` to get the same report, screenshots and replays described above. You can also drag a
`trace.zip` from it onto https://trace.playwright.dev, which works on a phone too.

The app only publishes from `main` when the unit, speed and GUI checks all pass.

## When something fails: what to send

Any one of these is enough to track a problem down:

- the name of the failed test and the error message (copy it from PowerShell or the report), or
- a screenshot of the report's page for that test, or
- the link to the failed check on GitHub.

## Adding a test

A GUI test is a list of steps. Here is a full one, from `tuner.spec.ts`:

```ts
test("starts and stops listening", async ({ page }) => {
  await openScreen(page, "tuner");                                        // tap Tuner on the home screen
  await page.click("#tuner-toggle");                                      // tap Start listening
  await expect(page.locator("#tuner-toggle")).toHaveText("Stop listening");
  await page.click("#tuner-toggle");                                      // tap it again
  await expect(page.locator("#tuner-readout")).toHaveText("Not listening");
});
```

`#tuner-toggle` is the button's `id` in `app/index.html`. To check a new screen or window for dead buttons, open it
in a test and add `await expectNothingBlocking(page, "a name for this step")`.

`npx playwright codegen http://localhost:5173` (with `npm run dev` running) opens the app and writes the test steps
for you as you click around. It's a quick way to start a new test.
