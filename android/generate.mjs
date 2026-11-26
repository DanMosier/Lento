// Generates the Android (Trusted Web Activity) project for Lento from twa-manifest.json into android/build/project.
// The APK just opens https://danmosier.github.io/Lento/ in Chrome, full screen, so every app update on GitHub Pages
// reaches the APK too. CI (.github/workflows/android.yml) runs this, then Gradle, then signs the APK.
//   node android/generate.mjs [versionCode]
// LENTO_ICON_BASE overrides where icons are downloaded from (for testing without network access to github.io).
import { TwaGenerator, TwaManifest, ConsoleLog } from "@bubblewrap/core";
import { readFile, rm, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const json = JSON.parse(await readFile(path.join(here, "twa-manifest.json"), "utf8"));
const code = Number(process.argv[2] || json.appVersionCode);
json.appVersionCode = code;
json.appVersionName = `1.0.${code}`;
json.appVersion = json.appVersionName;
if (process.env.LENTO_ICON_BASE) {
  json.iconUrl = `${process.env.LENTO_ICON_BASE}/icon-512.png`;
  json.maskableIconUrl = `${process.env.LENTO_ICON_BASE}/icon-512.png`;
  delete json.webManifestUrl;
}
const out = path.join(here, "build", "project");
await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });
const manifest = new TwaManifest(json);
const errors = manifest.validate();
if (errors) throw new Error(`twa-manifest.json: ${errors}`);
await new TwaGenerator().createTwaProject(out, manifest, new ConsoleLog("lento"));
console.log(`Android project for Lento ${json.appVersionName} written to ${out}`);
