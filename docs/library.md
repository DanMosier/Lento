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
  requests/                         "Make MusicXML" requests left by the app (the app's only writes)
  pieces/
    bach_cello-suite-1-prelude_bwv1007/
      bach_cello-suite-1-prelude_bwv1007__barenreiter.pdf
      bach_cello-suite-1-prelude_bwv1007__barenreiter.musicxml        same name as its PDF
      bach_cello-suite-1-prelude_bwv1007__barenreiter.quality.json    Lento_ConvertPDF's rating, if converted
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
```

**The watcher.** `lento-library watch` keeps running and looks at `requests/` every 30 seconds (`--interval` to
change). When the app queues a PDF, the watcher converts it and rebuilds `library.json`, so it shows up on the phone
after a Refresh. It writes `requests/_status.json` on every look; the app's Convert PDF screen reads it to show
whether the PC is on, what it is converting and what finished. A PDF that fails is set aside as
`requests/failed__<name>.json` (shown in the app as "last try failed"), so it isn't retried forever; queueing it again
tries once more. `--install` starts the watcher hidden at every Windows sign-in (a small file in your Startup folder,
logging to `requests/_watch.log`); `--uninstall` removes it. Run `--install` from the library folder, with the same
Python that has Lento_ConvertPDF installed.

`convert` runs Lento_ConvertPDF (homr on the GPU) as a separate program, saves each MusicXML beside its PDF, keeps any
MusicXML that already exists, clears the finished requests and rebuilds `library.json`. You can still use
Lento_ConvertPDF's own window for a batch; run `lento-library build` afterwards so the app sees the results.

## In the app

Settings > Google Drive library: paste the folder's Drive link and your Google client ID, then **Connect to Google
Drive**. After that, **Refresh** in the Library or Convert PDF screen picks up a new `library.json`.

- Each edition shows **PDF** (opens in Drive's viewer). If it has MusicXML it also shows **Practice**, which opens it
  in the Practice tab; a **check** or **unreliable** badge means the MusicXML was converted automatically and may
  have wrong notes.
- Without MusicXML, **Make MusicXML** asks your PC to convert it.
- **Convert PDF** (from the home screen) lists every PDF without MusicXML with a checkbox, **Select all shown**
  (follows the search) and **Queue for my PC**. It also shows the watcher's status and what is waiting.
- Scores you have opened are saved on the device (✓) and open offline. The last index is saved too.
- The app reads your Drive and can only create its own request files (the `drive.file` permission does not let it
  open or change anything it did not create).

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

The client ID is not a secret. To build it into the app instead of pasting it on each device, add a repository
variable `VITE_GOOGLE_CLIENT_ID` (or put it in `app/.env.local` for local builds).
