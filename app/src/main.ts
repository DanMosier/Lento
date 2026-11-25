/**
 * The Lento app shell: a home screen with a button per feature, and a Home button that is always visible.
 * Each feature is its own folder under src/ (practice/, library/, convert/, tuner/, settings/) and its own screen
 * here. Features never import each other; shared code lives in core/.
 */
import "./style.css";
import { $, onOpenScore } from "./core/app";
import { mark } from "./core/perf";
import { enterConvert } from "./convert/ui";
import { enterLibrary } from "./library/ui";
import { closeScore, enterPractice, hasScore } from "./practice/ui";
import { enterSettings } from "./settings/ui";
import { enterTuner, leaveTuner } from "./tuner/ui";

const NAMES: Record<string, string> = { home: "", practice: "Practice", library: "Library", convert: "Convert PDF", tuner: "Tuner", settings: "Settings" };
const SCREENS = Object.keys(NAMES);
const onEnter: Record<string, () => void> = {
  practice: enterPractice,
  library: () => void enterLibrary(),
  convert: enterConvert,
  tuner: enterTuner,
  settings: enterSettings,
};
const onLeave: Record<string, () => void> = { tuner: leaveTuner };

let current = "";

function show(name: string): void {
  if (name === current) return;
  if (current) onLeave[current]?.();
  for (const s of SCREENS) $(`view-${s}`).hidden = s !== name;
  current = name;
  $("screen-name").textContent = NAMES[name];
  document.title = name === "home" ? "Lento" : `${NAMES[name]} · Lento`;
  onEnter[name]?.();
  window.scrollTo(0, 0);
}

/** Opens a feature from home. It gets a history entry, so the phone's Back button returns home. */
function go(name: string): void {
  if (name === current) return;
  if (current === "home") history.pushState({ screen: name }, "", `#${name}`);
  else history.replaceState({ screen: name }, "", `#${name}`);
  show(name);
}

/** Going home closes an open score, so ask first. */
function confirmLeave(): Promise<boolean> {
  if (current !== "practice" || !hasScore()) return Promise.resolve(true);
  const d = $<HTMLDialogElement>("leave-dialog");
  return new Promise((resolve) => {
    d.returnValue = "";
    d.addEventListener("close", () => resolve(d.returnValue === "ok"), { once: true });
    d.showModal();
  });
}

async function goHome(): Promise<void> {
  if (current === "home") return;
  if (!(await confirmLeave())) return;
  if (current === "practice") closeScore();
  if (history.state?.screen) history.back(); // pops the entry made by go(); popstate then shows home
  else {
    history.replaceState(null, "", location.pathname);
    show("home");
  }
}

window.addEventListener("popstate", async () => {
  const target = (history.state?.screen as string | undefined) ?? "home";
  if (target === current) return;
  if (target === "home" && current === "practice" && hasScore()) {
    // Back button with a score open: stay unless the user confirms
    if (!(await confirmLeave())) {
      history.pushState({ screen: "practice" }, "", "#practice");
      return;
    }
    closeScore();
  }
  show(SCREENS.includes(target) ? target : "home");
});

$("home-btn").addEventListener("click", () => void goHome());
document.addEventListener("click", (e) => {
  const b = (e.target as Element).closest<HTMLElement>("[data-go]");
  if (b) go(b.dataset.go!);
});
onOpenScore(() => go("practice"));

try {
  localStorage.removeItem("lento.score"); // older versions kept the last score here; the app now starts at home
} catch {
  /* storage blocked */
}
// The app always starts at home.
history.replaceState(null, "", location.pathname);
show("home");
mark("ready");
