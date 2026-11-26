# Lento for Android

The APK is a **Trusted Web Activity (TWA)**: a thin Android app that opens https://danmosier.github.io/Lento/ full
screen in Chrome. The same web app runs on PC, phone and tablet, so the phone and tablet layouts, the microphone,
offline use and Google Drive sign-in all behave exactly as in the browser. Updates to the web app reach the APK
automatically; the APK itself only needs rebuilding when something in `android/` changes.

- `twa-manifest.json`: app id `io.github.danmosier.lento`, colours, icon, orientation (any, so tablets rotate).
- `generate.mjs`: turns that into an Android project with Google's Bubblewrap (`@bubblewrap/core`).
- `.github/workflows/android.yml`: generates, builds and signs the APK on every change to `android/`, and publishes
  it as a GitHub release: **android-latest** from `main`, **android-preview** from other branches.

## Installing

On the phone or tablet open the release page, download `Lento.apk`, open it, and allow installing from that source
if Android asks. Chrome must be installed (it is on almost every Android device).

## One-time setup for a permanent install

Until these are done, each build is signed with a new throwaway key (a newer build can't install over an older
one, so uninstall first) and Chrome shows a thin URL bar at the top.

1. **Signing key.** On a computer with Java (`keytool`) installed:
   ```
   keytool -genkeypair -keystore lento-release.keystore -alias lento -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Lento"
   ```
   Use the same password for store and key. Then add two repository secrets in GitHub
   (Settings → Secrets and variables → Actions): `ANDROID_KEYSTORE_BASE64` = the keystore as base64
   (PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("lento-release.keystore"))`) and
   `ANDROID_KEYSTORE_PASSWORD`. Keep the keystore file somewhere safe and out of the repo: losing it means
   reinstalling the app, and Play Store updates need it.
2. **Remove the URL bar.** Chrome only hides it if the site lists the app's key at
   `https://danmosier.github.io/.well-known/assetlinks.json`. That path belongs to a separate repository named
   `DanMosier.github.io` (GitHub Pages user site). Create it, add an empty `.nojekyll` file (so the `.well-known`
   folder is served) and `.well-known/assetlinks.json` copied from the latest release (built after step 1).

## Play Store (optional, later)

Bubblewrap can also make an `.aab` bundle (`./gradlew bundleRelease`). Uploading needs a Google Play developer
account (one-time US$25). The internal testing track is enough for personal use.
