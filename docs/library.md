# Score library (Google Drive)

Your scores live in one Google Drive folder. You organize it on your PC (Google Drive for Desktop shows it as a normal
folder), and the app's **Library** tab reads it on your phone, tablet or PC.

## Layout

```
Lento Library/                      the folder you connect in the app
  library.json                      index the app reads; made by `lento-library build`, don't edit by hand
  catalog.csv                       one row per PDF: composer, title, edition, technique tags (edit in Excel)
  tags.md                           the allowed technique tags
  inbox/                            new downloads waiting to be filed
  requests/                         "Make MusicXML" requests left by the app
  pieces/
    bach_cello-suite-1-prelude_bwv1007/
      bach_cello-suite-1-prelude_bwv1007__barenreiter.pdf
      bach_cello-suite-1-prelude_bwv1007__barenreiter.musicxml        same name as its PDF
      bach_cello-suite-1-prelude_bwv1007__barenreiter.quality.json    Lento_ConvertPDF's rating, if converted
      bach_cello-suite-1-prelude_bwv1007__barenreiter.marks.json      your fingerings, bowings and notes (made by the app)
```

- **piece_id** (the folder name): `composer_short-title[_catalog]`, lowercase, hyphens inside a part,
  e.g. `saint-saens_the-swan`, `faure_elegie_op24`. The practice list uses the same id.
- **Files:** `<piece_id>__<variant>.pdf` (variant = edition or part, e.g. `imslp-grutzmacher`, `cello-part`).
  MusicXML sits right beside its PDF with the same name (`.musicxml` or `.mxl`). That pairing is how the library
  knows which PDFs have MusicXML: `library.json` marks each PDF with its MusicXML, and each piece with `"musicxml": true/false`.
- A piece with no catalog row still shows up, named from its id.

## On the PC

```powershell
cd "G:\My Drive\Lento Library"                      # wherever Drive for Desktop shows the folder
lento-library add inbox\download.pdf faure_elegie_op24 imslp   # file a new PDF and add its catalog row
lento-library check                                 # find misnamed files, missing catalog rows, unknown tags
lento-library build                                 # rewrite library.json; run after any change
lento-library convert                               # make MusicXML for the PDFs requested from the app
lento-library convert --missing                     # ...or for every PDF that has none yet
lento-library convert faure_elegie_op24             # ...or for named pieces
lento-library watch --install                       # convert queued PDFs automatically whenever this PC is on
                                                    # (convert and watch also export MuseScore files: see below)
```

**The watcher.** `lento-library watch` keeps running and looks at `requests/` every 30 seconds (`--interval` to
change). When the app queues a PDF, the watcher converts it and rebuilds `library.json`, so it shows up on the phone
after a Refresh. It also rebuilds `library.json` when it starts and whenever score files, `catalog.csv` or `tags.md`
change by hand (added, moved or renamed in Drive), so `lento-library build` is never needed while it runs. It writes `requests/_status.json` on every look; the app's Convert PDF screen reads it to show
whether the PC is on, what it is converting and what finished. A PDF that fails is set aside as
`requests/failed__<name>.json` (shown in the app as "last try failed"), so it isn't retried forever; queueing it again
tries once more. `--install` starts the watcher hidden at every Windows sign-in (a small file in your Startup folder,
logging to `requests/_watch.log`); `--uninstall` removes it. If Google Drive isn't running yet when you sign in, the
watcher waits for the library folder to appear (the tray icon is grey meanwhile) and starts once Drive mounts it. Run `--install` from the library folder, with the same
Python that has Lento_ConvertPDF installed.

**The tray icon.** On Windows the installed watcher shows a small round icon with a note in the system tray (next to
the clock; Windows may tuck it under the ^ arrow, and you can drag it out to keep it in view). It is teal while the
watcher waits and amber while homr converts (or MuseScore exports). Hovering shows the piece being converted, how far
the batch is and about how long is left, and a notification pops up as each piece finishes or fails. Its menu opens
the library folder, the log and the app; **Quit watcher** stops the watcher, ending a conversion under way (that PDF
stays queued and converts the next time the watcher starts). The icon is fed the watcher's status directly, so it
reads no files and does no work between updates. Run `lento-library watch --tray` to get it in a window you started
yourself, or `--install --no-tray` to start at sign-in without it.

**MuseScore files.** Put a MuseScore file (`.mscz`, or the older `.mscx`) in a piece folder, named like the others
(`<piece_id>__<variant>.mscz`; `lento-library add` files it from the inbox too). `convert` and the watcher export it to
a MusicXML and a PDF of the same name beside it, using MuseScore itself without opening its window, add a catalog row
for the PDF, and rebuild `library.json`. These exports are exact, so the app shows a green **MuseScore** badge instead of
"check". Changing the MuseScore file exports it again. MuseScore 4 (or 3) must be installed on the PC; it is found in
the usual install folder, or give `--musescore "C:\path\to\MuseScore4.exe"` (or set `LENTO_MUSESCORE`). If it isn't
installed, the app's Convert PDF screen says so. All the files go in one MuseScore run, because it is slow to start.

`convert` runs Lento_ConvertPDF (homr on the GPU) as a separate program, saves each MusicXML beside its PDF, keeps any
MusicXML that already exists, clears the finished requests and rebuilds `library.json`. You can still use
Lento_ConvertPDF's own window for a batch; run `lento-library build` afterwards so the app sees the results.

## Piece details: genre, era, year, instrumentation, level

`catalog.csv` has columns for `year`, `genre`, `instrumentation` and `level`, which the app's Library table shows,
sorts and filters by. Fill them by hand, or from a spreadsheet saved as CSV (for a Google Sheet: File > Download >
Comma-separated values):

```powershell
lento-library details "Cello Sheet Music Library Catalog.csv"            # matches pieces, writes catalog-import-report.csv
lento-library details "Cello Sheet Music Library Catalog.csv" --apply    # then fills catalog.csv and rebuilds library.json
```

The sheet needs a composer and a title column (`Composer` and `Score Name`/`Title`, or one `Composer & Piece Title`
column like "J.S. Bach - Minuet in C"). It reads `Year Written`, `Genre / Era`, `Instrumentation / Ensemble` and
`Phase / Level` (and similar names). Each piece is matched by the composer's surname and the closest title, ignoring
"(Cello Part)" and "(Piano Score)"; only empty fields are filled (`--overwrite` replaces them), and "Unknown" is
left empty. The report lists every piece, what it matched and what was filled, so you can check before `--apply`.

## Filing an existing folder

An existing score folder (say one folder per composer, files named any old way) is filed into `pieces/` in batches,
one top folder at a time, with nothing moving until you say so:

```
lento-library organize plan --root "G:\My Drive\Sheet Music\Cello"     # writes organize-plan.csv, moves nothing
lento-library organize status --root ...                               # the batches, and how many files each
lento-library organize apply "Villa-Lobos, Heitor" --root ...          # files that one batch
lento-library organize undo "Villa-Lobos, Heitor" --root ...           # puts it back
```

`organize-plan.csv` has one row per score file: its batch, the `piece_id` and `variant` it will get, and `action`.
Open it in Excel or Sheets, fix any ids (files with the same `piece_id` become editions of one piece), and set
`action` to `skip` for anything that should stay put. Running `plan` again adds new files and keeps your edits.
`apply` checks the whole batch first, so one bad id moves nothing; it then moves the files (a PDF's MusicXML and
quality report move with it), adds catalog rows with the composer and the original name as the title, logs every
move to `organize-log.csv` and rebuilds `library.json`.

## In the app

Settings > Google Drive library: paste the folder's Drive link (the client ID is already filled in), then **Connect to
Google Drive**. Or open `https://danmosier.github.io/Lento/?library=<folder link>` once on each device, which saves the
folder, and press Connect in Settings. After that, **Refresh** in the Library or Convert PDF screen picks up a new `library.json`.

- The **Library** is a table: title, composer, genre / era, year, instrumentation, level, key, technique, number of
  PDFs and whether there is MusicXML. Tap a column heading to sort by it (again to reverse); the menus above filter
  by genre, instrumentation, level, technique and MusicXML, and the search box looks in every column. On a phone,
  swipe the table sideways; the title stays put. Tap a piece to open its details and editions.
- Each edition shows **PDF** (opens in Drive's viewer). If it has MusicXML it also shows **Practice**, which opens it
  in the Practice tab; a **check** or **unreliable** badge means the MusicXML was converted automatically and may
  have wrong notes.
- Without MusicXML, **Make MusicXML** asks your PC to convert it.
- **Convert PDF** (from the home screen) lists every PDF without MusicXML with a checkbox, **Select all shown**
  (follows the search) and **Queue for my PC**. It also shows the watcher's status and what is waiting.
- Its **Queue** tab shows what your PC is converting now, with a progress bar and a time estimate (from how long
  recent conversions took), the rest of the batch in the order it will convert, a bar for the whole batch, what was
  queued too late for this batch, and what finished recently. It checks on the PC every 15 seconds while it is open,
  and nothing runs when it isn't.
  Tick queued pieces and press **Remove from queue** to take them off: the app bins their request files (from the
  Drive bin they can be restored for 30 days), the PC skips them, and they go back to the Choose PDFs list. The piece
  converting now can't be stopped half way. Requests made on the PC itself can't be removed from the app (Drive only
  lets it change files it made); delete those in `requests/` on the PC.
- Scores you have opened are saved on the device (✓) and open offline. The last index is saved too.
- **Marks** in Practice (fingerings, bowings, string numbers, lifts, circles and short notes) are saved beside the
  MusicXML as `<name>.marks.json`, so they follow you between PC, phone and tablet. The score file itself is never
  changed. Offline, marks are kept on the device and uploaded the next time that score opens online; if two
  devices both changed them, the most recent change wins.
- The app reads your Drive and can only create and change its own files, the request files and marks files (the
  `drive.file` permission does not let it open or change anything it did not create).

## One-time setup: a Google client ID (about 5 minutes)

The app runs entirely in your browser, so Google needs to know it is allowed to ask for your Drive.

1. Go to https://console.cloud.google.com/, sign in, and create a project (e.g. "Lento").
2. **APIs & Services > Library**: enable **Google Drive API**.
3. **APIs & Services > OAuth consent screen** (Google Auth Platform): app name "Lento", your email, audience
   **External**, and under **Test users** add your own Google account. Leave it in **Testing**; it's only for you.
4. **Data access**: add the scopes `.../auth/drive.readonly` and `.../auth/drive.file`.
5. **Clients > Create client**: type **Web application**. Under **Authorized JavaScript origins** add
   `https://danmosier.github.io` and `http://localhost:5173`. Create, then copy the **Client ID**
   (it ends in `.apps.googleusercontent.com`).
6. Paste it in the app's Library settings. The first sign-in shows "Google hasn't verified this app"; that's expected
   for your own testing app: choose **Continue**.

The client ID is not a secret, and the one for danmosier.github.io is built into the app
(`app/src/core/library/connection.ts`). A fork can set its own with a repository variable `VITE_GOOGLE_CLIENT_ID`, in
`app/.env.local`, or in Settings.
