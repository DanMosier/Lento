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
  pieces/
    bach_cello-suite-1-prelude_bwv1007/
      bach_cello-suite-1-prelude_bwv1007__barenreiter.pdf
      bach_cello-suite-1-prelude_bwv1007.musicxml
```

- **piece_id** (the folder name): `composer_short-title[_catalog]`, lowercase, hyphens inside a part,
  e.g. `saint-saens_the-swan`, `faure_elegie_op24`. The practice list uses the same id.
- **Files:** `<piece_id>__<variant>.pdf` (variant = edition or part, e.g. `imslp-grutzmacher`, `cello-part`).
  MusicXML is `<piece_id>.musicxml` or `<piece_id>__<variant>.musicxml` / `.mxl`, next to its PDF.
- A piece with no catalog row still shows up, named from its id.

## On the PC

```powershell
cd "G:\My Drive\Lento Library"                      # wherever Drive for Desktop shows the folder
lento-library add inbox\download.pdf faure_elegie_op24 imslp   # file a new PDF and add its catalog row
lento-library check                                 # find misnamed files, missing catalog rows, unknown tags
lento-library build                                 # rewrite library.json; run after any change
```

Lento_ConvertPDF can save MusicXML straight into the piece's folder. Run `lento-library build` afterwards so the app
sees it.

## In the app

Library tab > Library settings: paste the folder's Drive link and your Google client ID, then **Connect to Google
Drive**. After that, **Refresh** picks up a new `library.json`.

- **Practice** opens the MusicXML in the Practice tab. **PDF** opens the PDF in Drive's viewer.
- Scores you have opened are saved on the device (✓) and open offline. The last index is saved too.
- The app asks for read-only Drive access and never changes your files.

## One-time setup: a Google client ID (about 5 minutes)

The app runs entirely in your browser, so Google needs to know it is allowed to ask for your Drive.

1. Go to https://console.cloud.google.com/, sign in, and create a project (e.g. "Lento").
2. **APIs & Services > Library**: enable **Google Drive API**.
3. **APIs & Services > OAuth consent screen** (Google Auth Platform): app name "Lento", your email, audience
   **External**, and under **Test users** add your own Google account. Leave it in **Testing**; it's only for you.
4. **Data access**: add the scope `.../auth/drive.readonly`.
5. **Clients > Create client**: type **Web application**. Under **Authorized JavaScript origins** add
   `https://danmosier.github.io` and `http://localhost:5173`. Create, then copy the **Client ID**
   (it ends in `.apps.googleusercontent.com`).
6. Paste it in the app's Library settings. The first sign-in shows "Google hasn't verified this app"; that's expected
   for your own testing app: choose **Continue**.

The client ID is not a secret. To build it into the app instead of pasting it on each device, add a repository
variable `VITE_GOOGLE_CLIENT_ID` (or put it in `app/.env.local` for local builds).
