/**
 * The Settings screen: options shared by the whole app. Each is a saved value other screens read when they open
 * (tuning "a4", headphone delay "avDelay", instrument sounds "sound", room sound "room", your own note-judging windows, and the
 * Google Drive library connection).
 */
import { $, sharedAudio, store } from "../core/app";
import { auth, clientId, findLibrary, library, libraryChanged, libraryFolder, saveConnection } from "../core/library/connection";
import { SOUND_CACHE } from "../core/sounds";
import { mb, midiOutName, midiSupported, removeSoundFont, saveSoundFont, setMidiOutName, soundFontInfo } from "../core/user-sounds";
import { roomOn } from "../core/room";
import { customPitch, customTiming, saveCustomPitch, saveCustomTiming } from "../core/tolerance";
import { publishedVersion, reloadToNewest, VERSION, versionLabel } from "../core/version";
import { clearProblems, problems } from "../core/diag";

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
  sfBox: $("set-sf-box"),
  sfFile: $<HTMLInputElement>("set-sf-file"),
  sfPick: $<HTMLButtonElement>("set-sf-pick"),
  sfRemove: $<HTMLButtonElement>("set-sf-remove"),
  sfStatus: $("set-sf-status"),
  midiBox: $("set-midi-box"),
  midiOut: $<HTMLSelectElement>("set-midi-out"),
  midiFind: $<HTMLButtonElement>("set-midi-find"),
  midiTest: $<HTMLButtonElement>("set-midi-test"),
  midiStatus: $("set-midi-status"),
  goodCents: $<HTMLInputElement>("set-good-cents"),
  okCents: $<HTMLInputElement>("set-ok-cents"),
  timingMs: $<HTMLInputElement>("set-timing-ms"),
  toleranceStatus: $("set-tolerance-status"),
  version: $("set-version"),
  checkUpdate: $<HTMLButtonElement>("set-check-update"),
  updateStatus: $("set-update-status"),
  problems: $("set-problems"),
  clearProblems: $<HTMLButtonElement>("set-clear-problems"),
};

function showProblems(): void {
  const list = problems().reverse();
  ui.problems.replaceChildren(
    ...list.map((p) => {
      const li = document.createElement("li");
      const when = new Date(p.at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
      li.textContent = p.text;
      const small = document.createElement("small");
      small.textContent = `${when} · version ${p.version}`;
      li.append(small);
      return li;
    }),
  );
  if (!list.length) ui.problems.replaceChildren(Object.assign(document.createElement("li"), { textContent: "Nothing so far." }));
  ui.clearProblems.hidden = !list.length;
}

ui.version.textContent = versionLabel();
ui.checkUpdate.addEventListener("click", async () => {
  ui.checkUpdate.disabled = true;
  say(ui.updateStatus, "Checking…");
  const v = await publishedVersion();
  ui.checkUpdate.disabled = false;
  if (!v) return say(ui.updateStatus, "Couldn't check (offline?).", "error");
  if (v.commit === VERSION.commit) return say(ui.updateStatus, "This is the newest version.");
  say(ui.updateStatus, `Version ${versionLabel(v)} is out. Reloading…`);
  void reloadToNewest();
});
ui.clearProblems.addEventListener("click", () => {
  clearProblems();
  showProblems();
});

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

ui.sound.addEventListener("change", () => {
  store.set("sound", ui.sound.value);
  showOwnSound();
});

/** Shows the SoundFont or MIDI options under the menu when one of them is chosen. */
function showOwnSound(): void {
  ui.sfBox.hidden = ui.sound.value !== "soundfont";
  ui.midiBox.hidden = ui.sound.value !== "midi";
  if (!ui.sfBox.hidden) showSoundFont();
  if (!ui.midiBox.hidden) showMidi();
}

function showSoundFont(): void {
  const info = soundFontInfo();
  ui.sfRemove.hidden = !info;
  ui.sfPick.textContent = info ? "Choose a different SoundFont…" : "Choose a SoundFont…";
  if (!ui.sfStatus.textContent || ui.sfStatus.dataset.kind !== "error")
    say(ui.sfStatus, info ? `Using ${info.name} (${mb(info.bytes)}).` : "No SoundFont chosen yet: playback uses the synth until you pick one.");
}

ui.sfPick.addEventListener("click", () => ui.sfFile.click());
ui.sfFile.addEventListener("change", async () => {
  const file = ui.sfFile.files?.[0];
  ui.sfFile.value = "";
  if (!file) return;
  ui.sfPick.disabled = true;
  say(ui.sfStatus, `Saving ${file.name}…`);
  try {
    const info = await saveSoundFont(file);
    say(ui.sfStatus, `Using ${info.name} (${mb(info.bytes)}). It loads the next time you press Play.`);
  } catch (e) {
    const full = e instanceof DOMException && e.name === "QuotaExceededError";
    say(ui.sfStatus, full ? "There isn't enough free space on this device for that file. Try a smaller (.sf3) one." : (e as Error).message, "error");
  } finally {
    ui.sfPick.disabled = false;
    ui.sfRemove.hidden = !soundFontInfo();
  }
});
ui.sfRemove.addEventListener("click", async () => {
  await removeSoundFont();
  say(ui.sfStatus, "SoundFont removed. Playback uses the synth until you pick another.");
  showSoundFont();
});

function showMidi(): void {
  ui.midiFind.disabled = ui.midiTest.disabled = !midiSupported();
  if (!midiSupported()) say(ui.midiStatus, "This browser can't send MIDI. Open Lento in Chrome or Edge to use this.", "error");
  else if (ui.midiOut.options.length <= 1 && !ui.midiOut.value) {
    const name = midiOutName();
    if (name) ui.midiOut.replaceChildren(new Option(name, name, true, true));
  }
}

async function findMidi(): Promise<void> {
  ui.midiFind.disabled = true;
  say(ui.midiStatus, "Looking for MIDI outputs…");
  try {
    const { midiOutputs } = await import("../core/midi-out");
    const outs = await midiOutputs();
    const saved = midiOutName();
    ui.midiOut.replaceChildren(...outs.map((o) => new Option(o.name ?? "MIDI output", o.name ?? "", false, o.name === saved)));
    if (!outs.length) {
      ui.midiOut.replaceChildren(new Option("No MIDI outputs found", ""));
      say(ui.midiStatus, "No MIDI outputs found. Start loopMIDI (or plug in your MIDI device) and press Find again.", "error");
    } else {
      if (!outs.some((o) => o.name === saved)) setMidiOutName(ui.midiOut.value);
      say(ui.midiStatus, `Found ${outs.length} MIDI output${outs.length > 1 ? "s" : ""}. Notes go to ${ui.midiOut.value}.`);
    }
  } catch {
    say(ui.midiStatus, "MIDI access was blocked. Allow MIDI for this site in the browser's site settings, then press Find again.", "error");
  } finally {
    ui.midiFind.disabled = false;
  }
}
ui.midiFind.addEventListener("click", () => void findMidi());
ui.midiOut.addEventListener("change", () => {
  setMidiOutName(ui.midiOut.value);
  say(ui.midiStatus, `Notes go to ${ui.midiOut.value}.`);
});
ui.midiTest.addEventListener("click", async () => {
  try {
    const { midiOutVoice } = await import("../core/midi-out");
    const voice = await midiOutVoice(sharedAudio(), midiOutName());
    if (!voice) return say(ui.midiStatus, "No MIDI output to test. Press Find MIDI outputs first.", "error");
    voice.test();
    say(ui.midiStatus, `Sent a middle C to ${voice.port.name}. If you heard nothing, check that your plugin host is listening to it.`);
  } catch {
    say(ui.midiStatus, "MIDI access was blocked. Allow MIDI for this site in the browser's site settings.", "error");
  }
});
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
  showOwnSound();
  ui.room.checked = roomOn();
  showTolerance();
  showProblems();
  if (!ui.driveStatus.textContent) say(ui.driveStatus, library() ? "A library folder is set." : "No library folder yet.");
}
