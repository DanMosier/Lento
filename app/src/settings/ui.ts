/**
 * The Settings screen: options shared by the whole app. Each is a saved value other screens read when they open
 * (tuning "a4", headphone delay "avDelay", instrument sounds "sound", room sound "room", your own note-judging windows, and the
 * Google Drive library connection).
 */
import { $, store } from "../core/app";
import { auth, clientId, findLibrary, library, libraryChanged, libraryFolder, saveConnection } from "../core/library/connection";
import { SOUND_CACHE } from "../core/sounds";
import { roomOn } from "../core/room";
import { customPitch, customTiming, saveCustomPitch, saveCustomTiming } from "../core/tolerance";

const ui = {
  folder: $<HTMLInputElement>("set-folder"),
  client: $<HTMLInputElement>("set-client"),
  connect: $<HTMLButtonElement>("set-connect"),
  signOut: $<HTMLButtonElement>("set-signout"),
  driveStatus: $("set-drive-status"),
  a4: $<HTMLInputElement>("set-a4"),
  delay: $<HTMLInputElement>("set-delay"),
  delayOut: $<HTMLOutputElement>("set-delay-out"),
  sound: $<HTMLSelectElement>("set-sound"),
  room: $<HTMLInputElement>("set-room"),
  clearSounds: $<HTMLButtonElement>("set-clear-sounds"),
  soundStatus: $("set-sound-status"),
  goodCents: $<HTMLInputElement>("set-good-cents"),
  okCents: $<HTMLInputElement>("set-ok-cents"),
  timingMs: $<HTMLInputElement>("set-timing-ms"),
  toleranceStatus: $("set-tolerance-status"),
};

function say(el: HTMLElement, text: string, kind: "info" | "error" = "info"): void {
  el.textContent = text;
  el.dataset.kind = kind;
}

ui.connect.addEventListener("click", async () => {
  saveConnection(ui.folder.value, ui.client.value);
  if (!ui.folder.value.trim()) {
    // no link given: sign in and look for the library in Drive
    ui.connect.disabled = true;
    say(ui.driveStatus, "Looking for your library in Google Drive…");
    try {
      if (!(await findLibrary())) {
        ui.connect.disabled = false;
        return say(ui.driveStatus, "Couldn't find a library (a folder with library.json) in your Drive. Paste the folder's link above.", "error");
      }
      ui.folder.value = libraryFolder();
    } catch (e) {
      ui.connect.disabled = false;
      return say(ui.driveStatus, (e as Error).message, "error");
    }
  }
  const lib = library();
  if (!lib) return say(ui.driveStatus, "That doesn't look like a Google Drive folder link.", "error");
  ui.connect.disabled = true;
  say(ui.driveStatus, "Connecting…");
  try {
    const index = await lib.loadIndex();
    say(ui.driveStatus, `Connected: ${index.pieces.length} pieces in the library.`);
    libraryChanged();
  } catch (e) {
    say(ui.driveStatus, (e as Error).message, "error");
  } finally {
    ui.connect.disabled = false;
    ui.signOut.hidden = !(auth.signedIn || auth.remembered);
  }
});
ui.signOut.addEventListener("click", () => {
  auth.signOut();
  ui.signOut.hidden = true;
  say(ui.driveStatus, "Signed out. Scores saved on this device still open offline.");
});

ui.a4.addEventListener("change", () => {
  const v = Math.max(415, Math.min(466, Math.round(+ui.a4.value || 440)));
  ui.a4.value = String(v);
  store.set("a4", String(v));
});

function showDelay(): void {
  const v = +ui.delay.value;
  ui.delayOut.value = v === 0 ? "off" : `${v > 0 ? "+" : ""}${v} ms`;
}
ui.delay.addEventListener("input", () => {
  showDelay();
  store.set("avDelay", +ui.delay.value);
});

function showTolerance(): void {
  const p = customPitch();
  ui.goodCents.value = String(p.good);
  ui.okCents.value = String(p.ok);
  ui.okCents.min = String(p.good + 1);
  ui.timingMs.value = String(customTiming());
}
for (const input of [ui.goodCents, ui.okCents])
  input.addEventListener("change", () => {
    const p = saveCustomPitch({ good: +ui.goodCents.value, ok: +ui.okCents.value });
    showTolerance();
    say(ui.toleranceStatus, `Practice now judges pitch as in tune within ±${p.good} cents and slightly off within ±${p.ok}.`);
  });
ui.timingMs.addEventListener("change", () => {
  const ms = saveCustomTiming(+ui.timingMs.value);
  showTolerance();
  say(ui.toleranceStatus, `Practice now flags notes more than ${ms} ms early or late.`);
});

ui.sound.addEventListener("change", () => store.set("sound", ui.sound.value));
ui.room.addEventListener("change", () => store.set("room", ui.room.checked));
ui.clearSounds.addEventListener("click", async () => {
  try {
    await caches.delete(SOUND_CACHE);
    say(ui.soundStatus, "Downloaded sounds removed. They download again the next time a score needs them.");
  } catch {
    say(ui.soundStatus, "Nothing to remove.");
  }
});

/** Called when the screen opens: show the current values (another screen may have changed them). */
export function enterSettings(): void {
  ui.folder.value = libraryFolder();
  ui.client.value = clientId();
  ui.signOut.hidden = !(auth.signedIn || auth.remembered);
  ui.a4.value = store.get<string>("a4") ?? "440";
  ui.delay.value = String(store.get<number>("avDelay") ?? 0);
  showDelay();
  ui.sound.value = store.get<string>("sound") ?? "auto";
  ui.room.checked = roomOn();
  showTolerance();
  if (!ui.driveStatus.textContent) say(ui.driveStatus, library() ? "A library folder is set." : "No library folder yet.");
}
