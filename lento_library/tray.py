"""A Windows system tray icon for the watcher: shows at a glance whether homr is converting.

The icon is teal while the watcher waits and amber while it converts PDFs or exports MuseScore files. Hovering shows
what it is doing ("Converting Elegie, Fauré (2 of 5), about 4 min left"), and a notification pops up as each piece
finishes. The menu opens the library folder, the log and the app, and quits the watcher.

It runs in the watcher's own process and is fed the same dict the watcher writes to requests/_status.json, so it
never reads the (Drive-synced) file and costs nothing between updates: it only touches the icon when its picture,
hover text or results actually change. Needs pystray (installed with the package on Windows); without it the watcher
simply runs with no icon.
"""

from __future__ import annotations

import json
import os
import threading
import traceback
import webbrowser
from pathlib import Path
from typing import Callable

from lento_library.library import INDEX_NAME, REQUESTS, title_from_id

APP_URL = "https://danmosier.github.io/Lento/"
TIP_MAX = 127  # Windows cuts tray hover text at 128 characters
COLORS = {"idle": (38, 132, 128), "busy": (226, 140, 28), "stopped": (128, 128, 128)}


def available() -> bool:
    try:
        import pystray  # noqa: F401
    except Exception:  # not installed, or no desktop to show it on
        return False
    return True


def icon_image(state: str, size: int = 64):
    """A round badge with a white eighth note, in the state's color."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((1, 1, size - 2, size - 2), fill=COLORS.get(state, COLORS["stopped"]) + (255,))
    s = size / 64
    white = (255, 255, 255, 255)
    d.ellipse((17 * s, 38 * s, 33 * s, 50 * s), fill=white)  # note head
    d.rectangle((29 * s, 14 * s, 33 * s, 45 * s), fill=white)  # stem
    d.polygon([(33 * s, 14 * s), (46 * s, 24 * s), (44 * s, 30 * s), (33 * s, 22 * s)], fill=white)  # flag
    return img


def minutes(seconds: float) -> str:
    if seconds < 60:
        return "under a minute left"
    m = round(seconds / 60)
    return f"about {m} min left" if m < 60 else f"about {m // 60} h {m % 60} min left"


class Names:
    """PDF file name -> "Title, Composer", from library.json (read again only when it changes)."""

    def __init__(self, root: Path):
        self.path = root / INDEX_NAME
        self.stamp: float | None = None
        self.names: dict[str, str] = {}

    def __call__(self, file: str) -> str:
        try:
            stamp = self.path.stat().st_mtime
            if stamp != self.stamp:
                self.stamp = stamp
                pieces = json.loads(self.path.read_text(encoding="utf-8")).get("pieces", [])
                self.names = {f["name"]: f"{p['title']}, {p['composer']}" for p in pieces for f in p.get("files", [])}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return self.names.get(file) or title_from_id(file.split("__")[0].rsplit(".", 1)[0])


def describe(data: dict, name: Callable[[str], str]) -> tuple[str, str]:
    """(icon state, hover text) for a status dict."""
    state = data.get("state")
    if state == "converting":
        busy = data.get("current_files") or ([data["current"]] if data.get("current") else [])
        batch = data.get("batch") or {}
        tip = f"Lento: converting {name(busy[0])}" if busy else "Lento: converting"
        page = data.get("page") or {}
        if busy and page.get("pdf") == busy[0] and page.get("pages", 0) > 1:
            tip += f", page {page['page']} of {page['pages']}"
        total, done = batch.get("total", 0), batch.get("done", 0)
        if total > 1:
            tip += f" (piece {min(done + 1, total)} of {total})"
        avg = data.get("avg_s")
        if avg and total:
            # the PDF converting now is (page - 1) / pages through, when homr says which page it is on
            through = (page["page"] - 1) / page["pages"] if busy and page.get("pdf") == busy[0] and page.get("pages") else 0
            tip += f", {minutes(avg * (max(1, total - done) - through))}"
        return "busy", tip
    if state == "exporting":
        return "busy", f"Lento: exporting {data.get('current') or 'MuseScore files'} with MuseScore"
    if state == "stopped":
        return "stopped", "Lento: watcher stopped"
    if state == "waiting":
        return "stopped", "Lento: waiting for Google Drive (the library folder isn't there yet)"
    last = next((r for r in reversed(data.get("results", [])) if r.get("ok")), None)
    tip = "Lento: waiting for PDFs to convert"
    return "idle", tip + (f". Last: {name(last['pdf'])}" if last else "")


def finished_message(r: dict, name: Callable[[str], str], data: dict) -> tuple[str, str]:
    """(title, text) of the notification for one result."""
    what = name(r["pdf"])
    batch = data.get("batch") or {}
    of = f" ({batch['done']} of {batch['total']})" if batch.get("total", 0) > 1 else ""
    took = f" in {round(r['seconds'] / 60)} min" if r.get("seconds", 0) >= 90 else ""
    if r.get("ok"):
        kind = "Exported" if r["pdf"].lower().endswith((".mscz", ".mscx")) else "Converted"
        return f"{kind}{of}", f"{what}{took}. The MusicXML is in the library."
    why = r.get("error") or "see the log"
    return f"Couldn't convert{of}", f"{what}: {why}"


class Tray:
    """The icon. update() is called from the watcher's thread with each status dict; the icon lives in the main thread."""

    def __init__(self, root: Path, log: Path | None, on_quit: Callable[[], None]):
        import pystray

        self.root, self.log, self.on_quit = root, log, on_quit
        self.images = {k: icon_image(k) for k in COLORS}
        self.names = Names(root)
        self.state, self.tip = "idle", "Lento: starting"
        self.seen: set[tuple] | None = None  # results already shown (None until the first update)
        self.lock = threading.Lock()
        item = pystray.MenuItem
        self.icon = pystray.Icon(
            "lento-watcher",
            self.images["idle"],
            self.tip,
            pystray.Menu(
                item(lambda _: self.menu_line(), None, enabled=False),
                pystray.Menu.SEPARATOR,
                item("Open library folder", lambda: self.open(self.root), default=True),
                item("Open log", lambda: self.open(self.log), visible=lambda _: bool(self.log and self.log.exists())),
                item("Open Lento app", lambda: webbrowser.open(APP_URL)),
                pystray.Menu.SEPARATOR,
                item("Quit watcher", self.quit),
            ),
        )

    def run(self, work: Callable[[], None]) -> None:
        """Shows the icon and runs `work` (the watcher) in a background thread until it returns or Quit is chosen."""

        def setup(icon) -> None:
            icon.visible = True

            def go() -> None:
                try:
                    work()
                except Exception:
                    traceback.print_exc()
                    self.set("stopped", "Lento: watcher stopped after an error (see the log)")
                    self.notify("Lento watcher stopped", "It hit an error. The log has the details.")
                finally:
                    icon.stop()

            threading.Thread(target=go, name="watcher", daemon=True).start()

        self.icon.run(setup)

    def update(self, data: dict) -> None:
        with self.lock:
            if data.get("state") == "restarting":
                self.notify("Lento updated", f"{data.get('update', 'New version')}. Restarting with it now.")
                return
            state, tip = describe(data, self.names)
            self.set(state, tip)
            if "results" not in data:  # waiting for the library folder: nothing to compare yet
                return
            results = data["results"]
            keys = {(r.get("pdf"), r.get("at")) for r in results}
            if self.seen is not None:
                for r in results:
                    if (r.get("pdf"), r.get("at")) not in self.seen:
                        self.notify(*finished_message(r, self.names, data))
            self.seen = keys

    def set(self, state: str, tip: str) -> None:
        tip = tip if len(tip) <= TIP_MAX else tip[: TIP_MAX - 1] + "…"
        if state != self.state:
            self.state = state
            self.icon.icon = self.images[state]
        if tip != self.tip:
            self.tip = tip
            self.icon.title = tip
            try:
                self.icon.update_menu()  # the menu's first line repeats the hover text
            except NotImplementedError:  # a backend that can't (not Windows)
                pass

    def menu_line(self) -> str:
        line = self.tip.removeprefix("Lento: ")
        return line[:1].upper() + line[1:]

    def notify(self, title: str, text: str) -> None:
        try:
            self.icon.notify(text[:250], title[:60])
        except Exception as e:  # notifications turned off or unsupported: the icon still shows the state
            print(f"couldn't show a notification: {e}", flush=True)

    def open(self, path: Path | None) -> None:
        if path and hasattr(os, "startfile"):
            os.startfile(path)  # type: ignore[attr-defined]

    def quit(self) -> None:
        self.set("stopped", "Lento: stopping…")
        self.on_quit()


def log_path(root: Path) -> Path:
    return root / REQUESTS / "_watch.log"
