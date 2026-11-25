"""The watcher's tray icon, with a stand-in for pystray so it runs anywhere, plus the watcher's stop support."""

from __future__ import annotations

import json
import sys
import threading
import time
import types
from pathlib import Path

from lento_library import tray, watch
from lento_library.library import Library


class FakeIcon:
    def __init__(self, name, icon, title, menu):
        self.icon, self.title, self.menu = icon, title, menu
        self.notes: list[tuple[str, str]] = []
        self.icon_changes = 0
        self.stopped = False

    def __setattr__(self, k, v):
        if k == "icon" and "icon" in self.__dict__:
            self.__dict__["icon_changes"] += 1
        super().__setattr__(k, v)

    def notify(self, text, title):
        self.notes.append((title, text))

    def update_menu(self):
        pass

    def run(self, setup):
        setup(self)
        while not self.stopped:
            time.sleep(0.01)

    def stop(self):
        self.stopped = True


def fake_pystray(monkeypatch) -> None:
    class Menu(tuple):
        SEPARATOR = None

        def __new__(cls, *items):
            return tuple.__new__(cls, items)

    mod = types.SimpleNamespace(Icon=FakeIcon, Menu=Menu, MenuItem=lambda *a, **k: (a, k))
    monkeypatch.setitem(sys.modules, "pystray", mod)


def write_index(root: Path) -> None:
    (root / "library.json").write_text(json.dumps({"pieces": [
        {"title": "Elegie", "composer": "Fauré", "files": [{"name": "faure_elegie__imslp.pdf"}]},
    ]}), encoding="utf-8")


def test_describe_and_names(tmp_path: Path) -> None:
    write_index(tmp_path)
    names = tray.Names(tmp_path)
    assert names("faure_elegie__imslp.pdf") == "Elegie, Fauré"
    assert names("popper_hungarian-rhapsody_op68__x.pdf") == "Hungarian rhapsody, OP68"  # not in the index yet
    busy = {"state": "converting", "current_files": ["faure_elegie__imslp.pdf"], "batch": {"total": 5, "done": 1}, "avg_s": 120}
    assert tray.describe(busy, names) == ("busy", "Lento: converting Elegie, Fauré (piece 2 of 5), about 8 min left")
    paged = {**busy, "page": {"pdf": "faure_elegie__imslp.pdf", "page": 3, "pages": 4}}
    assert tray.describe(paged, names)[1] == "Lento: converting Elegie, Fauré, page 3 of 4 (piece 2 of 5), about 7 min left"
    assert tray.describe({"state": "idle", "results": []}, names) == ("idle", "Lento: waiting for PDFs to convert")
    idle = {"state": "idle", "results": [{"pdf": "faure_elegie__imslp.pdf", "ok": True}]}
    assert tray.describe(idle, names)[1].endswith("Last: Elegie, Fauré")
    assert tray.describe({"state": "exporting", "current": "a.mscz"}, names)[0] == "busy"


def test_icon_images_are_drawn() -> None:
    img = tray.icon_image("busy")
    assert img.size == (64, 64) and img.getpixel((32, 4))[:3] == tray.COLORS["busy"]
    assert img.getpixel((31, 30))[:3] == (255, 255, 255)  # the note's stem


def test_tray_follows_status_and_notifies_each_finished_piece(tmp_path: Path, monkeypatch) -> None:
    fake_pystray(monkeypatch)
    write_index(tmp_path)
    t = tray.Tray(tmp_path, None, lambda: None)
    icon = t.icon
    old = [{"pdf": "old__x.pdf", "ok": True, "at": "1"}]
    t.update({"state": "idle", "results": old})
    assert icon.notes == []  # results from before it started aren't announced
    busy = {"state": "converting", "current_files": ["faure_elegie__imslp.pdf"], "batch": {"total": 2, "done": 0}, "results": old}
    t.update(busy)
    t.update(busy)  # nothing new: the icon isn't touched again
    assert icon.icon_changes == 1 and icon.title.startswith("Lento: converting Elegie")
    done = [*old, {"pdf": "faure_elegie__imslp.pdf", "ok": True, "at": "2", "seconds": 300}]
    t.update({**busy, "current_files": ["b__x.pdf"], "batch": {"total": 2, "done": 1}, "results": done})
    assert icon.notes == [("Converted (1 of 2)", "Elegie, Fauré in 5 min. The MusicXML is in the library.")]
    t.update({"state": "idle", "results": [*done, {"pdf": "b__x.pdf", "ok": False, "at": "3"}]})
    assert icon.notes[-1] == ("Couldn't convert", "b: see the log") and icon.icon_changes == 2
    t.update({"state": "idle", "results": [{"pdf": "x" * 300, "ok": True, "at": "4"}]})
    assert len(icon.title) <= tray.TIP_MAX


def test_watcher_feeds_the_tray_and_quits_from_it(tmp_path: Path, monkeypatch) -> None:
    fake_pystray(monkeypatch)
    (tmp_path / "pieces").mkdir()
    lib = Library(tmp_path)
    stop = threading.Event()
    t = tray.Tray(tmp_path, None, stop.set)
    seen: list[str] = []

    def update(data: dict) -> None:
        seen.append(data["state"])
        t.update(data)
        if data["state"] == "idle":
            t.quit()  # Quit from the menu after the first look

    started = time.monotonic()
    t.run(lambda: watch.run(lib, ["true"], "no", interval=30, stop=stop, on_status=update))
    assert time.monotonic() - started < 5  # didn't wait out the 30 s interval
    assert seen[-1] == "stopped" and t.icon.stopped
    assert json.loads((tmp_path / "requests" / "_status.json").read_text(encoding="utf-8"))["state"] == "stopped"


def test_stop_ends_a_conversion_and_keeps_its_request(tmp_path: Path) -> None:
    from lento_library.cli import convert_pdfs

    folder = tmp_path / "pieces" / "slow_piece"
    folder.mkdir(parents=True)
    pdf = folder / "slow_piece__x.pdf"
    pdf.write_bytes(b"%PDF")
    (tmp_path / "requests").mkdir()
    (tmp_path / "requests" / "convert__slow_piece__x.json").write_text("{}")
    slow = tmp_path / "slow.py"
    slow.write_text("import time\ntime.sleep(30)\n")
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    started = time.monotonic()
    assert convert_pdfs(Library(tmp_path), [pdf], [sys.executable, str(slow)], "no", stop=stop) == []
    assert time.monotonic() - started < 5
    assert (tmp_path / "requests" / "convert__slow_piece__x.json").exists()  # still queued, not failed
    assert not list((tmp_path / "requests").glob("failed__*"))


def test_finish_corrects_a_piece_reported_converted_without_musicxml(tmp_path: Path) -> None:
    (tmp_path / "pieces").mkdir()
    status = watch.Status(Library(tmp_path), 30)
    pdfs = [tmp_path / "pieces" / "a" / "a__x.pdf"]
    batch = watch.Batch(status, pdfs)
    batch.folder(1, 1, pdfs[0].parent, pdfs)
    batch.line("a__x.pdf", "converted", 10.0)
    assert status.data["results"][-1]["ok"] is True  # shown as soon as the converter reports it
    batch.finish({"a__x.pdf"})
    assert [(r["pdf"], r["ok"]) for r in status.data["results"]] == [("a__x.pdf", False)]


def test_install_starts_with_the_tray_unless_asked_not_to(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    startup = tmp_path / "appdata" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True)
    watch.install(tmp_path)
    assert "--tray" in (startup / "Lento library watcher.vbs").read_text(encoding="utf-8")
    watch.install(tmp_path, tray=False)
    assert "--tray" not in (startup / "Lento library watcher.vbs").read_text(encoding="utf-8")


def test_watcher_waits_for_the_library_folder_then_logs_there(tmp_path: Path, monkeypatch) -> None:
    fake_pystray(monkeypatch)
    root = tmp_path / "G" / "Cello"  # Google Drive hasn't mounted it yet
    lib = Library(root)
    log = root / "requests" / "_watch.log"
    stop = threading.Event()
    t = tray.Tray(root, log, stop.set)
    monkeypatch.setattr(watch, "WAIT_CHECK", 0.05)
    states: list[str] = []

    def update(data: dict) -> None:
        states.append(data["state"])
        t.update(data)
        if data["state"] == "idle":
            stop.set()

    threading.Timer(0.2, lambda: (root / "pieces").mkdir(parents=True)).start()
    out, err = sys.stdout, sys.stderr
    try:
        t.run(lambda: watch.run(lib, ["true"], "no", interval=30, stop=stop, on_status=update, log=log))
    finally:
        sys.stdout.flush()
        sys.stdout, sys.stderr = out, err
    assert states[0] == "waiting" and "idle" in states and states[-1] == "stopped"
    assert "watching" in log.read_text(encoding="utf-8")  # the log opens once the folder is there
    assert t.icon.notes == []


def test_install_has_python_open_the_log(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    startup = tmp_path / "appdata" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True)
    watch.install(tmp_path / "not-mounted-yet")
    vbs = (startup / "Lento library watcher.vbs").read_text(encoding="utf-8")
    assert "cmd /c" not in vbs and "--log" in vbs and "_watch.log" in vbs
    assert not (tmp_path / "not-mounted-yet").exists()  # installing doesn't need the folder


def test_pages_and_failure_reasons_reach_the_status_and_the_index(tmp_path: Path) -> None:
    import sys as _sys

    folder = tmp_path / "pieces" / "bad_piece"
    folder.mkdir(parents=True)
    (folder / "bad_piece__x.pdf").write_bytes(b"%PDF")
    (tmp_path / "requests").mkdir()
    (tmp_path / "requests" / "convert__bad_piece__x.json").write_text("{}")
    fake = tmp_path / "fake.py"
    fake.write_text(
        "print('      page 1/2: bad_piece__x.pdf', flush=True)\n"
        "print('      page 2/2: bad_piece__x.pdf', flush=True)\n"
        "print('[1/1] FAILED: bad_piece__x.pdf -> homr could not read page 2: No staffs found (4.0s)', flush=True)\n"
    )
    seen: list[dict] = []
    lib = Library(tmp_path)
    assert watch.run(lib, [_sys.executable, str(fake)], "no", once=True, on_status=lambda d: seen.append(json.loads(json.dumps(d)))) == 0
    assert any(d.get("page") == {"pdf": "bad_piece__x.pdf", "page": 2, "pages": 2} for d in seen)
    status = json.loads((tmp_path / "requests" / "_status.json").read_text(encoding="utf-8"))
    assert "page" not in status
    assert status["results"][-1]["error"] == "homr could not read page 2: No staffs found"
    entry = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))["pieces"][0]["files"][0]
    assert entry["convert_failed"] is True and entry["convert_error"] == "homr could not read page 2: No staffs found"
