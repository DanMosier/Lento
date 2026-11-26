/**
 * The Lento app shell: a home screen with a button per feature, and a Home button that is always visible.
 * Each feature is its own folder under src/ (practice/, library/, convert/, tuner/, settings/) and its own screen
 * here. Features never import each other; shared code lives in core/.
 */
import "./style.css";
import { $, onOpenScore, store } from "./core/app";
import { mark, timed } from "./core/perf";
import { note, watchProblems } from "./core/diag";
import { newerVersion, reloadToNewest } from "./core/version";

watchProblems();

/** A bar offering to reload, when a newer version of the app has been published (or a piece of it failed to load). */
function offerReload(text: string, button = true): void {
  if (document.getElementById("update-bar")) return;
  const bar = document.createElement("div");
  bar.id = "update-bar";
  bar.className = "update-bar";
  bar.setAttribute("role", "status");
  const msg = document.createElement("span");
  msg.textContent = text;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "primary";
  btn.textContent = "Reload";
  btn.addEventListener("click", () => {
    btn.disabled = true;
    btn.textContent = "Reloading…";
    void reloadToNewest();
  });
  bar.append(msg);
  if (button) bar.append(btn);
  document.body.append(bar);
}

/**
 * Each feature's code loads the first time its screen opens, so adding features doesn't slow the app's start.
 * (Practice also loads when a score is sent to it from the Library.)
 */
interface Feature {
  enter?: () => void;
  leave?: () => void;
  hasScore?: () => boolean;
  closeScore?: () => void;
}
const LOAD: Record<string, () => Promise<Feature>> = {
  practice: () => import("./practice/ui").then((m) => ({ enter: m.enterPractice, hasScore: m.hasScore, closeScore: m.closeScore })),
  library: () => import("./library/ui").then((m) => ({ enter: () => void m.enterLibrary() })),
  convert: () => import("./convert/ui").then((m) => ({ enter: m.enterConvert })),
  tuner: () => import("./tuner/ui").then((m) => ({ enter: m.enterTuner, leave: m.leaveTuner })),
  settings: () => import("./settings/ui").then((m) => ({ enter: m.enterSettings })),
};
const features = new Map<string, Promise<Feature>>();
const feature = (name: string): Promise<Feature> | null => {
  if (!LOAD[name]) return null;
  let f = features.get(name);
  if (!f) {
    f = timed(`load-${name}`, LOAD[name]);
    features.set(name, f);
    f.catch((e) => {
      // Usually an update replaced the app's files on the server: try again next time, and offer a reload.
      features.delete(name);
      note("error", `Could not load ${name}: ${(e as Error)?.message ?? e}`);
      offerReload("Lento was updated. Reload to continue.");
    });
  }
  return f;
};
const loadedFeatures = new Map<string, Feature>(); // the ones that have finished loading

const NAMES: Record<string, string> = { home: "", practice: "Practice", library: "Library", convert: "Convert PDF", tuner: "Tuner", settings: "Settings" };
const SCREENS = Object.keys(NAMES);

let current = "";
let shows = 0; // counts screen changes, so a delayed check can tell whether anything happened since

function show(name: string): void {
  if (name === current) return;
  if (current) loadedFeatures.get(current)?.leave?.();
  for (const s of SCREENS) $(`view-${s}`).hidden = s !== name;
  current = name;
  shows++;
  $("screen-name").textContent = NAMES[name];
  document.title = name === "home" ? "Lento" : `${NAMES[name]} · Lento`;
  window.scrollTo(0, 0);
  void feature(name)?.then((f) => {
    loadedFeatures.set(name, f);
    if (current === name) f.enter?.();
    mark(`entered-${name}`);
  });
}

const practice = (): Feature | undefined => loadedFeatures.get("practice");

/** Opens a feature from home. It gets a history entry, so the phone's Back button returns home. */
function go(name: string): void {
  if (name === current) return;
  if (current === "home") history.pushState({ screen: name }, "", `#${name}`);
  else history.replaceState({ screen: name }, "", `#${name}`);
  show(name);
}

/** Going home closes an open score, so ask first. */
function confirmLeave(): Promise<boolean> {
  if (current !== "practice" || !practice()?.hasScore?.()) return Promise.resolve(true);
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
  if (current === "practice") practice()?.closeScore?.();
  if (history.state?.screen) {
    const before = shows;
    history.back(); // pops the entry made by go(); popstate then shows home
    // An embedded page (such as Drive's PDF viewer) can add history entries of its own, and then Back only steps
    // back inside it. Home must always work, so go home directly if Back didn't change the screen.
    window.setTimeout(() => {
      if (shows === before) {
        history.replaceState(null, "", location.pathname);
        show("home");
      }
    }, 350);
  } else {
    history.replaceState(null, "", location.pathname);
    show("home");
  }
}

window.addEventListener("popstate", async () => {
  const target = (history.state?.screen as string | undefined) ?? "home";
  if (target === current) return;
  if (target === "home" && current === "practice" && practice()?.hasScore?.()) {
    // Back button with a score open: stay unless the user confirms
    if (!(await confirmLeave())) {
      history.pushState({ screen: "practice" }, "", "#practice");
      return;
    }
    practice()?.closeScore?.();
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
// A setup link (…/Lento/?library=<Drive folder link or id>) connects this device to a library folder in one tap,
// so the folder never has to be typed on a phone.
{
  const lib = new URLSearchParams(location.search).get("library");
  if (lib) store.set("library.folder", lib);
}
// The app always starts at home.
history.replaceState(null, "", location.pathname);
show("home");
mark("ready");

/**
 * Always the newest version: the app opens at once from its offline copy, then asks the server (in the background)
 * whether a newer version is out. If so, and nothing would be lost (on the home screen, or Practice with no score
 * open), it switches to it by itself; otherwise a Reload bar offers it. Offline, nothing happens. Each version is
 * tried once per session, so a server still handing out the old files can't cause a reload loop.
 */
function safeToReload(): boolean {
  return current === "home" || (current === "practice" && !practice()?.hasScore?.());
}
async function checkForUpdate(): Promise<void> {
  const commit = await newerVersion();
  if (!commit) return;
  let tried = false;
  try {
    tried = sessionStorage.getItem("lento.updateTried") === commit;
    sessionStorage.setItem("lento.updateTried", commit);
  } catch {
    tried = true; // can't remember trying: never risk a loop
  }
  if (!tried && safeToReload()) {
    offerReload("Updating Lento…", false);
    await reloadToNewest();
  } else offerReload("A new version of Lento is ready.");
}
void checkForUpdate();
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void checkForUpdate();
});
