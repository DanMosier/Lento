"""The background watcher: converts PDFs queued from the app whenever this PC is on.

It looks at requests/ in the library folder (kept in sync with Google Drive by Drive for Desktop) every few
seconds. When requests appear it runs the converter on them, then rebuilds library.json, so the phone sees the
new MusicXML after its next refresh. It writes requests/_status.json on every look, which the app reads to show
whether the PC is online and what it is doing.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import sys
import time
from pathlib import Path

from lento_library.library import REQUESTS, Library

STATUS = "_status.json"
KEEP_RESULTS = 20


def now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class Status:
    """requests/_status.json: what the PC is doing, for the app to show."""

    def __init__(self, lib: Library, interval: float):
        self.path = lib.root / REQUESTS / STATUS
        self.data: dict = {"format": "lento-watch", "version": 1, "pc": platform.node(), "interval_s": interval, "results": []}
        try:  # keep earlier results across restarts
            old = json.loads(self.path.read_text(encoding="utf-8"))
            self.data["results"] = list(old.get("results", []))[-KEEP_RESULTS:]
        except (OSError, ValueError):
            pass

    def write(self, state: str, queue: list[str], current: str | None = None) -> None:
        self.data.update(state=state, queue=queue, current=current, heartbeat=now())
        self.path.parent.mkdir(exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def result(self, pdf: str, ok: bool) -> None:
        self.data["results"] = [*self.data["results"], {"pdf": pdf, "ok": ok, "at": now()}][-KEEP_RESULTS:]


def run(lib: Library, cmd: list[str], gpu: str, interval: float = 30, once: bool = False, musescore: str | None = None) -> int:
    from lento_library.cli import convert_pdfs, export_musescore

    status = Status(lib, interval)
    tried: dict[Path, float] = {}  # MuseScore file -> its modified time when last exported or tried
    print(f"watching {lib.root / REQUESTS} every {interval:g} s (Ctrl+C to stop)", flush=True)
    try:
        while True:
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
            if pdfs:
                names = [p.name for p in pdfs]
                print(f"{len(pdfs)} PDF(s) queued", flush=True)

                def on_folder(i, n, folder, here):
                    status.write("converting", [x for x in names if x not in {p.name for p in here}], ", ".join(p.name for p in here))

                failed = set(convert_pdfs(lib, pdfs, cmd, gpu, on_folder))
                for p in pdfs:
                    status.result(p.name, p.name not in failed)
                lib.write_index()
                print(f"done: {len(pdfs) - len(failed)} converted, {len(failed)} failed", flush=True)
            status.write("idle", [])
            if once:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        status.write("stopped", [])
        print("stopped")
        return 0


def startup_file() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise OSError("--install works on Windows only. On other systems, start 'lento-library watch' from your login items.")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Lento library watcher.vbs"


def install(root: Path, interval: float = 30) -> str:
    """Starts the watcher hidden at every Windows sign-in, logging to <library>/requests/_watch.log."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
    log = root.resolve() / REQUESTS / "_watch.log"
    cmd = f'cmd /c ""{pyw}" -m lento_library watch --root "{root.resolve()}" --interval {interval:g} >> "{log}" 2>&1"'
    vbs = 'CreateObject("WScript.Shell").Run "' + cmd.replace('"', '""') + '", 0, False\n'
    f = startup_file()
    f.write_text(vbs, encoding="utf-8")
    return f"installed: the watcher starts at sign-in ({f}). Log: {log}. Start it now by signing out and in, or by running that file."


def uninstall() -> str:
    f = startup_file()
    if f.exists():
        f.unlink()
        return f"removed {f}. A watcher already running stops at the next sign-out."
    return "the watcher wasn't installed"
