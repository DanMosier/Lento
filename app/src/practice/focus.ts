/**
 * Score focus: hides the app header and the Practice controls so the score gets the whole screen (most useful on a
 * phone turned sideways), leaving one slim bar with Play/Stop, Record, full screen and a button to bring the
 * controls back. The slim bar's buttons press the real ones, so playback and recording behave exactly the same.
 */
import { $ } from "../core/app";

export interface FocusParts {
  view: HTMLElement;
  play: HTMLButtonElement;
  record: HTMLButtonElement;
  /** A short line about what will play, e.g. "70% · m. 1–24". */
  info: () => string;
}

export interface Focus {
  set: (on: boolean) => void;
  readonly on: boolean;
  refresh: () => void;
}

export function setUpFocus(p: FocusParts): Focus {
  const bar = $("mini-bar");
  const toggle = $<HTMLButtonElement>("focus-btn");
  const play = $<HTMLButtonElement>("mini-play");
  const record = $<HTMLButtonElement>("mini-record");
  const full = $<HTMLButtonElement>("mini-full");
  const info = $("mini-info");
  let on = false;

  // Copy the real buttons' label, look and enabled state whenever they change (cheap: a few changes per take).
  const mirror = (from: HTMLButtonElement, to: HTMLButtonElement) => {
    const copy = () => {
      to.textContent = from.textContent;
      to.disabled = from.disabled;
      to.classList.toggle("on", from.classList.contains("on"));
    };
    new MutationObserver(copy).observe(from, { childList: true, characterData: true, subtree: true, attributes: true, attributeFilter: ["disabled", "class"] });
    copy();
  };
  mirror(p.play, play);
  mirror(p.record, record);
  play.addEventListener("click", () => p.play.click());
  record.addEventListener("click", () => p.record.click());

  const canFull = !!document.documentElement.requestFullscreen && document.fullscreenEnabled !== false;
  full.hidden = !canFull;
  const fullLabel = () => {
    full.textContent = document.fullscreenElement ? "Exit full screen" : "Full screen";
  };
  full.addEventListener("click", () => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    else void document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
  });
  document.addEventListener("fullscreenchange", fullLabel);
  fullLabel();

  const refresh = () => {
    if (on) info.textContent = p.info();
  };
  const set = (v: boolean) => {
    if (v === on) return;
    on = v;
    p.view.classList.toggle("focus", on);
    bar.hidden = !on;
    toggle.setAttribute("aria-pressed", String(on));
    refresh();
    if (!on && document.fullscreenElement) void document.exitFullscreen().catch(() => {});
  };
  toggle.addEventListener("click", () => set(!on));
  $("mini-show").addEventListener("click", () => set(false));

  return {
    set,
    get on() {
      return on;
    },
    refresh,
  };
}
