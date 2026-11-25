"""The background watcher: converts PDFs queued from the app whenever this PC is on.

It looks at requests/ in the library folder (kept in sync with Google Drive by Drive for Desktop) every few
seconds. When requests appear it runs the converter on them, then rebuilds library.json, so the phone sees the
new MusicXML after its next refresh. It also rebuilds library.json whenever score files are added, moved or renamed
by hand (and once when it starts), so the index never needs a manual `lento-library build`. It writes requests/_status.json on every look, which the app reads to show
whether the PC is online and what it is doing.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from lento_library.library import REQUESTS, Library

STATUS = "_status.json"
KEEP_RESULTS = 20


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Status:
    """requests/_status.json: what the PC is doing, for the app to show.

    Besides the state and heartbeat it carries the batch being converted, in order: `queue` (still to come),
    `current_files` with `started` (converting now), `batch` (how many of how many are done) and `avg_s` (recent
    seconds per PDF, for the app's time estimate). The heartbeat is renewed every few seconds during a conversion.
    """

    def __init__(self, lib: Library, interval: float, on_save: Callable[[dict], None] | None = None):
        self.path = lib.root / REQUESTS / STATUS
        self.on_save = on_save  # the tray icon, fed the same data as the file
        self.data: dict = {"format": "lento-watch", "version": 2, "pc": platform.node(), "interval_s": interval, "results": []}
        try:  # keep earlier results across restarts
            old = json.loads(self.path.read_text(encoding="utf-8"))
            self.data["results"] = list(old.get("results", []))[-KEEP_RESULTS:]
        except (OSError, ValueError):
            pass

    def write(self, state: str, queue: list[str], current: str | None = None, **extra) -> None:
        if state in ("idle", "stopped"):
            for k in ("current_files", "started", "batch", "page"):
                self.data.pop(k, None)
        self.data.update(state=state, queue=queue, current=current, heartbeat=now(), avg_s=self.average(), **extra)
        self.save()

    def beat(self) -> None:
        """Renews the heartbeat without changing anything else (during a long conversion)."""
        self.data["heartbeat"] = now()
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:  # Drive for Desktop can hold the file for a moment; the next write catches up
            print(f"couldn't write {self.path.name}: {e}", flush=True)
        if self.on_save:
            try:
                self.on_save(self.data)
            except Exception as e:  # the icon must never stop a conversion
                print(f"tray icon: {e}", flush=True)

    def result(self, pdf: str, ok: bool, seconds: float | None = None, error: str | None = None) -> None:
        r: dict = {"pdf": pdf, "ok": ok, "at": now()}
        if seconds is not None:
            r["seconds"] = round(seconds, 1)
        if error and not ok:
            r["error"] = error[:300]
        self.data["results"] = [*self.data["results"], r][-KEEP_RESULTS:]

    def average(self) -> float | None:
        """Median seconds per converted PDF over the recent results, or None before any."""
        times = sorted(r["seconds"] for r in self.data["results"] if r.get("ok") and r.get("seconds"))
        return times[len(times) // 2] if times else None


class Batch:
    """Keeps _status.json up to date while a batch of PDFs converts: which one is converting, what's next."""

    def __init__(self, status: Status, pdfs: list[Path]):
        self.status = status
        self.order = [p.name for p in pdfs]  # conversion order: folder by folder, as convert_pdfs goes
        self.done: dict[str, tuple[bool, float | None]] = {}
        self.current: list[str] = []
        self.started, self.started_at = now(), time.monotonic()
        self.batch = {"total": len(pdfs), "done": 0, "started": now()}

    def write(self) -> None:
        busy = [n for n in self.current if n not in self.done]
        queue = [n for n in self.order if n not in self.done and n not in busy]
        self.batch["done"] = len(self.done)
        self.status.write("converting", queue, ", ".join(busy) or None, current_files=busy, started=self.started, batch=self.batch)

    def folder(self, i: int, n: int, folder: Path, here: list[Path]) -> None:
        self.current = [p.name for p in here]
        self.status.data.pop("page", None)
        self.started, self.started_at = now(), time.monotonic()
        self.write()

    def line(self, name: str, state: str, seconds: float, detail: str = "") -> None:
        """The converter reported one PDF; requested ones are marked done (its siblings are ignored) and added to
        the results right away, with the reason if it failed, so the app's Recent list and the tray's notification
        don't wait for the batch."""
        if name in self.current and name not in self.done:
            self.done[name] = (state == "converted", seconds)
            self.status.data.pop("page", None)
            self.status.result(name, state == "converted", seconds, detail)
            self.started, self.started_at = now(), time.monotonic()  # the next PDF in the folder starts now
            self.write()

    def removed(self, names: list[str]) -> None:
        """Taken off the queue in the app before their turn: they leave the batch without a result."""
        self.order = [n for n in self.order if n not in names]
        self.batch["total"] = len(self.order)
        self.write()

    def page(self, name: str, page: int, pages: int) -> None:
        """homr started a page of a PDF in the batch: `page` in the status says how far that PDF has got."""
        if name in self.current and name not in self.done:
            self.status.data["page"] = {"pdf": name, "page": page, "pages": pages}
            self.write()

    def tick(self) -> None:
        self.status.beat()

    def finish(self, failed: set[str]) -> None:
        """Adds a result for each PDF the converter didn't report, and corrects one it called converted that has
        no MusicXML after all."""
        for name in self.order:
            ok = name not in failed
            if name not in self.done:
                self.status.result(name, ok, error=None if ok else "the converter didn't report it; see the log")
            elif self.done[name][0] != ok:
                for r in reversed(self.status.data["results"]):
                    if r["pdf"] == name:
                        r["ok"] = ok
                        if not ok:
                            r["error"] = "no MusicXML was written"
                        break


RESTART = 3  # run()'s return code when it updated itself and should be started again
UPDATE_EVERY = 300.0  # seconds between looks for updates on GitHub (--auto-update), while idle
WAIT_CHECK = 10.0  # seconds between looks for a library folder that isn't there yet


def wait_for_library(lib: Library, stop: threading.Event | None = None, on_status: Callable[[dict], None] | None = None) -> bool:
    """Waits until the library folder is there. Google Drive for Desktop mounts G: a while after sign-in (or only
    once it is opened) and unmounts it when it quits, so the watcher may start before its folder exists.
    Returns False if `stop` was set while waiting."""
    if lib.root.is_dir():
        return True
    print(f"waiting for the library folder {lib.root} (is Google Drive running?)", flush=True)
    if on_status:
        on_status({"state": "waiting", "root": str(lib.root)})
    while not lib.root.is_dir():
        if stop is not None:
            if stop.wait(WAIT_CHECK):
                return False
        else:
            time.sleep(WAIT_CHECK)
    print("library folder found", flush=True)
    return True


def open_log(path: Path) -> None:
    """Sends this process's output to the log (appending). Done here rather than by the shell, so the watcher can
    start before Google Drive has mounted the library folder the log lives in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    sys.stdout = sys.stderr = f


def run(lib: Library, cmd: list[str], gpu: str, interval: float = 30, once: bool = False, musescore: str | None = None,
        stop: threading.Event | None = None, on_status: Callable[[dict], None] | None = None, log: Path | None = None,
        auto_update: bool = False) -> int:
    """Watches until Ctrl+C or until `stop` is set (the tray's Quit, which also ends a conversion under way; its
    requests stay queued for next time). on_status gets every status update. It first waits for the library
    folder if it isn't there (Google Drive not running yet), then sends its output to `log` if given. With
    auto_update it pulls merged changes from GitHub while idle and returns RESTART after updating."""
    from lento_library.cli import convert_pdfs, export_musescore

    try:
        if not wait_for_library(lib, stop, on_status):
            return 0
    except KeyboardInterrupt:
        return 0
    if log:
        open_log(log)
    status = Status(lib, interval, on_status)
    next_update = time.monotonic() + min(UPDATE_EVERY, 60)
    tried: dict[Path, float] = {}  # MuseScore file -> its modified time when last exported or tried
    built: tuple | None = None  # the library's fingerprint when library.json was last written
    print(f"watching {lib.root / REQUESTS} every {interval:g} s (Ctrl+C to stop)", flush=True)
    try:
        while True:
            if not lib.root.is_dir():  # Google Drive quit: wait for it to come back
                if not wait_for_library(lib, stop, on_status):
                    break
            wrote = False  # library.json written during this look
            stems = lib.requests()
            pdfs = [p for p in (lib.pdf_for(s) for s in stems) if p]
            for stem in stems:  # a request for a PDF that isn't there can never succeed
                if not lib.pdf_for(stem):
                    lib.fail_request(stem)
                    status.result(f"{stem}.pdf", False)
            # MuseScore files are exported as soon as they appear (or change); a failed one is tried again only
            # after it changes, so a broken file doesn't run MuseScore every few seconds
            pending = [p for p in lib.musescore_files() if tried.get(p) != p.stat().st_mtime]
            if pending:
                status.write("exporting", [p.name for p in pending], ", ".join(p.name for p in pending))
                exported, failed_ms, found = export_musescore(lib, musescore, None)
                status.data["musescore"] = found
                for p in pending:
                    tried[p] = p.stat().st_mtime
                for name in exported:
                    status.result(name, True)
                for name in failed_ms:
                    status.result(name, False)
                if exported:
                    lib.write_index()
                    wrote = True
            if pdfs:
                pdfs.sort(key=lambda p: (str(p.parent), p.name))  # the order convert_pdfs works in
                print(f"{len(pdfs)} PDF(s) queued", flush=True)
                batch = Batch(status, pdfs)
                failed = set(convert_pdfs(lib, pdfs, cmd, gpu, batch.folder, batch.line, batch.tick, requested_only=True, on_removed=batch.removed, stop=stop,
                                         on_page=batch.page))
                if stop and stop.is_set():
                    break
                batch.finish(failed)
                lib.write_index()
                wrote = True
                print(f"done: {len(pdfs) - len(failed)} converted, {len(failed)} failed", flush=True)
            # rebuilt above after a conversion or export, so this only fires for changes made by hand
            fp = lib.fingerprint()
            if fp != built and not wrote:
                _, n = lib.write_index()
                print(f"library changed: library.json rebuilt ({n} pieces)", flush=True)
            built = fp
            status.write("idle", [])
            if once:
                return 0
            if auto_update and time.monotonic() >= next_update:
                from lento_library import update

                next_update = time.monotonic() + UPDATE_EVERY
                subject = update.check()
                if subject:
                    if on_status:
                        on_status({"state": "restarting", "update": subject})
                    return RESTART
            if stop:
                if stop.wait(interval):
                    break
            else:
                time.sleep(interval)
    except KeyboardInterrupt:
        pass
    status.write("stopped", [])
    print("stopped", flush=True)
    return 0


def run_with_tray(lib: Library, cmd: list[str], gpu: str, interval: float = 30, musescore: str | None = None,
                  log: Path | None = None, auto_update: bool = False) -> int:
    """Runs the watcher with a tray icon (Windows), or without one when pystray isn't there."""
    from lento_library import tray

    if not tray.available():
        print("no tray icon (pystray isn't installed): watching without one", flush=True)
        return run(lib, cmd, gpu, interval, musescore=musescore, log=log, auto_update=auto_update)
    stop = threading.Event()
    icon = tray.Tray(lib.root, log or tray.log_path(lib.root), stop.set)
    code = [0]

    def work() -> None:
        code[0] = run(lib, cmd, gpu, interval, musescore=musescore, stop=stop, on_status=icon.update, log=log, auto_update=auto_update)

    icon.run(work)
    return code[0]


def startup_file() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise OSError("--install works on Windows only. On other systems, start 'lento-library watch' from your login items.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Lento library watcher.vbs"


def install(root: Path, interval: float = 30, tray: bool = True, auto_update: bool = True) -> str:
    """Starts the watcher hidden at every Windows sign-in (with its tray icon unless tray=False), logging to
    <library>/requests/_watch.log."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
    log = root.resolve() / REQUESTS / "_watch.log"
    flag = (" --tray" if tray else "") + (" --auto-update" if auto_update else "")
    # Python opens the log itself once the library folder is there: at sign-in Google Drive may not have mounted
    # G: yet, and a shell redirect into a missing folder would stop the watcher before it starts
    cmd = f'"{pyw}" -m lento_library watch --root "{root.resolve()}" --interval {interval:g}{flag} --log "{log}"'
    vbs = 'CreateObject("WScript.Shell").Run "' + cmd.replace('"', '""') + '", 0, False\n'
    f = startup_file()
    f.write_text(vbs, encoding="utf-8")
    icon = ", with its tray icon," if tray else ""
    if auto_update:
        icon += " updating itself from GitHub,"
    return f"installed: the watcher starts at sign-in{icon} ({f}). Log: {log}. Start it now by signing out and in, or by running that file."


def uninstall() -> str:
    f = startup_file()
    if f.exists():
        f.unlink()
        return f"removed {f}. A watcher already running stops at the next sign-out."
    return "the watcher wasn't installed"
