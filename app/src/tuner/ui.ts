/** The Tuner tab: live note and cents from the microphone, plus C G D A reference tones. */
import { $, sharedAudio, store } from "../core/app";
import { Tuner } from "./tuner";

const ui = {
  panel: $("tuner"),
  name: $("tuner-name"),
  octave: $("tuner-octave"),
  needle: $("tuner-needle"),
  readout: $("tuner-readout"),
  toggle: $<HTMLButtonElement>("tuner-toggle"),
  a4: $<HTMLInputElement>("tuner-a4"),
};
let tuner: Tuner | null = null;

const a4 = () => +ui.a4.value || 440;
const saved = store.get<string>("a4"); // the same tuning setting the Practice tab uses
if (saved) ui.a4.value = saved;
ui.a4.addEventListener("change", () => {
  store.set("a4", ui.a4.value);
  if (tuner) tuner.a4 = a4();
});

function get(): Tuner {
  if (!tuner) {
    tuner = new Tuner(sharedAudio(), a4());
    tuner.onReading = (r) => {
      if (!r) {
        ui.readout.textContent = "Play a note";
        ui.needle.style.left = "50%";
        ui.panel.dataset.state = "idle";
        return;
      }
      ui.name.textContent = r.name;
      ui.octave.textContent = String(r.octave);
      const c = Math.max(-50, Math.min(50, r.cents));
      ui.needle.style.left = `${50 + c}%`;
      ui.readout.textContent = `${r.cents > 0 ? "+" : ""}${r.cents.toFixed(0)} cents · ${r.hz.toFixed(1)} Hz`;
      ui.panel.dataset.state = Math.abs(r.cents) <= 5 ? "good" : Math.abs(r.cents) <= 15 ? "close" : "off";
    };
  }
  tuner.a4 = a4();
  return tuner;
}

function setListening(on: boolean): void {
  ui.toggle.textContent = on ? "Stop listening" : "Start listening";
  ui.toggle.setAttribute("aria-pressed", String(on));
}

ui.toggle.addEventListener("click", async () => {
  const t = get();
  if (t.running) {
    t.stop();
    setListening(false);
    ui.panel.querySelectorAll("[data-midi]").forEach((x) => x.setAttribute("aria-pressed", "false"));
    ui.readout.textContent = "Not listening";
    ui.panel.dataset.state = "idle";
    return;
  }
  try {
    await t.start();
    setListening(true);
    ui.readout.textContent = "Play a note";
  } catch (e) {
    ui.readout.textContent = `Could not use the microphone: ${(e as Error).message}`;
  }
});

ui.panel.querySelectorAll<HTMLButtonElement>("[data-midi]").forEach((b) =>
  b.addEventListener("click", () => {
    const on = b.getAttribute("aria-pressed") === "true";
    ui.panel.querySelectorAll("[data-midi]").forEach((x) => x.setAttribute("aria-pressed", "false"));
    const t = get();
    if (on) t.tone(null);
    else {
      b.setAttribute("aria-pressed", "true");
      t.tone(+b.dataset.midi!);
    }
  }),
);

/** Called when the user opens the tab: pick up a tuning change made in another tab. */
export function enterTuner(): void {
  const v = store.get<string>("a4");
  if (v) ui.a4.value = v;
}

/** Called when the user leaves the tab: release the microphone and silence any tone. */
export function leaveTuner(): void {
  if (!tuner) return;
  tuner.stop();
  setListening(false);
  ui.readout.textContent = "Not listening";
  ui.panel.dataset.state = "idle";
  ui.panel.querySelectorAll("[data-midi]").forEach((x) => x.setAttribute("aria-pressed", "false"));
}
