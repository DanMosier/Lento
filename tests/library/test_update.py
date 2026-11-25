"""The watcher's self-update from GitHub, against a local stand-in for the GitHub repository."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from lento_library import update, watch
from lento_library.library import Library


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def setup(tmp_path: Path) -> tuple[Path, Path]:
    """origin (bare, like GitHub), the PC's clone, and a second clone that 'merges' new work."""
    origin = tmp_path / "origin.git"
    sh(tmp_path, "init", "--bare", "-b", "main", str(origin))
    pc = tmp_path / "pc"
    sh(tmp_path, "clone", str(origin), str(pc))
    sh(pc, "config", "user.email", "t@example.com")
    sh(pc, "config", "user.name", "t")
    (pc / "a.py").write_text("x = 1\n")
    (pc / "pyproject.toml").write_text("[project]\n")
    sh(pc, "add", "-A")
    sh(pc, "commit", "-m", "first")
    sh(pc, "push", "-u", "origin", "main")
    other = tmp_path / "other"
    sh(tmp_path, "clone", str(origin), str(other))
    sh(other, "config", "user.email", "t@example.com")
    sh(other, "config", "user.name", "t")
    return pc, other


def merge_on_github(other: Path, name: str, text: str, msg: str) -> None:
    (other / name).write_text(text)
    sh(other, "add", name)
    sh(other, "commit", "-m", msg)
    sh(other, "push")


def test_pulls_merged_work_and_reinstalls_only_for_new_dependencies(tmp_path: Path, monkeypatch) -> None:
    pc, other = setup(tmp_path)
    installs = []
    monkeypatch.setattr(update, "reinstall", lambda repo: installs.append(repo))
    assert update.check(pc) is None  # nothing new
    merge_on_github(other, "a.py", "x = 2\n", "Tray: show pages")
    assert update.check(pc) == "Tray: show pages"
    assert (pc / "a.py").read_text() == "x = 2\n" and installs == []
    merge_on_github(other, "pyproject.toml", "[project]\nname = 'x'\n", "New dependency")
    assert update.check(pc) == "New dependency" and installs == [pc]


def test_local_edits_are_never_overwritten(tmp_path: Path, capsys) -> None:
    pc, other = setup(tmp_path)
    merge_on_github(other, "a.py", "x = 2\n", "new")
    (pc / "a.py").write_text("x = 'mine'\n")
    assert update.check(pc) is None
    assert (pc / "a.py").read_text() == "x = 'mine'\n"
    assert "local edits" in capsys.readouterr().out


def test_no_git_or_no_network_just_waits(tmp_path: Path, capsys) -> None:
    assert update.check(tmp_path) is None  # not a git checkout
    pc, _ = setup(tmp_path)
    sh(pc, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    assert update.check(pc) is None
    assert "couldn't check for updates" in capsys.readouterr().out


def test_restart_keeps_the_options() -> None:
    cmd = update.restart_command(["watch", "--root", "G:/Cello", "--tray", "--auto-update", "--log", "x.log"])
    assert cmd[1:] == ["-m", "lento_library", "watch", "--root", "G:/Cello", "--tray", "--auto-update", "--log", "x.log"]


def test_watcher_restarts_after_updating_while_idle(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pieces").mkdir()
    monkeypatch.setattr(watch, "UPDATE_EVERY", 0)
    monkeypatch.setattr(update, "check", lambda repo=None: "Tray: show pages")
    seen: list[dict] = []
    code = watch.run(Library(tmp_path), ["true"], "no", interval=30, on_status=seen.append, auto_update=True)
    assert code == watch.RESTART and seen[-1] == {"state": "restarting", "update": "Tray: show pages"}
    assert json.loads((tmp_path / "requests" / "_status.json").read_text(encoding="utf-8"))["state"] == "idle"


def test_install_turns_auto_update_on(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    startup = tmp_path / "appdata" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup.mkdir(parents=True)
    watch.install(tmp_path)
    assert "--auto-update" in (startup / "Lento library watcher.vbs").read_text(encoding="utf-8")
    watch.install(tmp_path, auto_update=False)
    assert "--auto-update" not in (startup / "Lento library watcher.vbs").read_text(encoding="utf-8")
