/** The part picker: which part to practise, and which others to show and play along. */
import { $ } from "../core/app";
import type { PartInfo } from "../core/score";

export interface PartChoice {
  practise: string; // part id
  shown: string[]; // part ids to draw and offer for play-along, in score order; includes `practise`
}

/** Shows the picker. Resolves with the choice, or null if the user cancels. */
export function pickParts(parts: PartInfo[], initial: PartChoice): Promise<PartChoice | null> {
  const dialog = $<HTMLDialogElement>("parts-dialog");
  const list = $("parts-list");
  const shown = new Set(initial.shown);
  let practise = initial.practise;
  const rows = parts.map((p) => {
    const radio = Object.assign(document.createElement("input"), { type: "radio", name: "practise", value: p.id, checked: p.id === practise });
    const box = Object.assign(document.createElement("input"), { type: "checkbox", value: p.id, checked: shown.has(p.id) || p.id === practise });
    radio.setAttribute("aria-label", `Practise ${p.name}`);
    box.setAttribute("aria-label", `Show ${p.name}`);
    const row = document.createElement("div");
    row.className = "parts-row";
    const name = document.createElement("span");
    name.textContent = p.name;
    row.append(name, radio, box);
    return { p, radio, box, row };
  });
  const sync = () => {
    for (const r of rows) {
      if (r.p.id === practise) r.box.checked = true;
      r.box.disabled = r.p.id === practise; // the practised part is always shown
    }
  };
  for (const r of rows)
    r.radio.addEventListener("change", () => {
      practise = r.p.id;
      sync();
    });
  sync();
  list.replaceChildren(...rows.map((r) => r.row));
  $("parts-none").onclick = () => rows.forEach((r) => (r.box.checked = r.p.id === practise));
  $("parts-all").onclick = () => rows.forEach((r) => (r.box.checked = true));

  return new Promise((resolve) => {
    dialog.returnValue = "";
    dialog.addEventListener(
      "close",
      () => resolve(dialog.returnValue === "ok" ? { practise, shown: rows.filter((r) => r.box.checked).map((r) => r.p.id) } : null),
      { once: true },
    );
    dialog.showModal();
    rows.find((r) => r.p.id === practise)?.radio.focus();
  });
}

/** A short label for the Parts button, like "Violoncello + 2". */
export function choiceLabel(parts: PartInfo[], c: PartChoice): string {
  const name = parts.find((p) => p.id === c.practise)?.name ?? c.practise;
  const extra = c.shown.length - 1;
  return extra > 0 ? `${name} + ${extra}` : name;
}

/** Keep only ids that exist in this score, in score order, with the practised part always included. */
export function cleanChoice(parts: PartInfo[], c: PartChoice): PartChoice | null {
  if (!parts.some((p) => p.id === c.practise)) return null;
  const want = new Set([...c.shown, c.practise]);
  return { practise: c.practise, shown: parts.filter((p) => want.has(p.id)).map((p) => p.id) };
}
