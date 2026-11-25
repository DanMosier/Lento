/**
 * The Lento app shell. Each feature is its own folder under src/ (practice/, tuner/) and its own tab here.
 * Features never import each other; shared code lives in core/.
 */
import "./style.css";
import { $ } from "./core/app";
import { enterPractice } from "./practice/ui";
import { enterTuner, leaveTuner } from "./tuner/ui";

const tabs = [...document.querySelectorAll<HTMLButtonElement>("[role=tab]")];
const onEnter: Record<string, () => void> = { practice: enterPractice, tuner: enterTuner };
const onLeave: Record<string, () => void> = { tuner: leaveTuner };

function show(name: string): void {
  for (const t of tabs) {
    const on = t.dataset.tab === name;
    t.setAttribute("aria-selected", String(on));
    const view = $(`view-${t.dataset.tab}`);
    if (!on && !view.hidden) onLeave[t.dataset.tab!]?.();
    if (on && view.hidden) onEnter[name]?.();
    view.hidden = !on;
  }
  if (location.hash !== `#${name}`) history.replaceState(null, "", name === "practice" ? location.pathname : `#${name}`);
}

for (const t of tabs) t.addEventListener("click", () => show(t.dataset.tab!));
show(location.hash === "#tuner" ? "tuner" : "practice");
