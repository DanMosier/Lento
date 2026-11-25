"""Keeps the PC's copy of Lento up to date, so a pull request merged on GitHub (from the phone, say) reaches the
watcher without anyone at the PC.

While idle, the watcher calls check() every few minutes. If the repository Lento runs from is behind its GitHub
branch and has no local edits, it fast-forwards (never merges or overwrites anything), reinstalls when
pyproject.toml changed (new dependencies), and tells the watcher to restart itself so the new code runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def git(repo: Path, *args: str, timeout: float = 120) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=timeout, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(out.stderr or out.stdout).strip().splitlines()[-1:] or ['failed']}")
    return out.stdout.strip()


def console_python() -> Path:
    """python.exe beside pythonw.exe: pip and uv want a console interpreter."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return exe.with_name("python.exe")
    return exe


def reinstall(repo: Path) -> None:
    """Installs the package again (editable) with whichever installer the venv has: uv venvs come without pip."""
    py = console_python()
    uv = shutil.which("uv")
    cmd = [uv, "pip", "install", "-e", str(repo), "--python", str(py)] if uv else [str(py), "-m", "pip", "install", "-e", str(repo)]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                         creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        raise RuntimeError(f"reinstall failed: {(out.stderr or out.stdout).strip()[-300:]}")


def check(repo: Path = REPO) -> str | None:
    """Pulls new commits if there are any. Returns what changed (the newest commit's subject) when it updated,
    None when there was nothing to do or it couldn't (the reason is printed for the log)."""
    if not (repo / ".git").exists():
        return None
    try:
        git(repo, "fetch", "--quiet")
        upstream = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
        behind = int(git(repo, "rev-list", "--count", f"HEAD..{upstream}") or 0)
        if not behind:
            return None
        if git(repo, "status", "--porcelain", "--untracked-files=no"):
            print(f"update: {behind} new commit(s) on {upstream}, but this copy has local edits; not updating", flush=True)
            return None
        old = git(repo, "rev-parse", "HEAD")
        git(repo, "merge", "--ff-only", "--quiet", upstream)
        changed = git(repo, "diff", "--name-only", old, "HEAD").splitlines()
        if "pyproject.toml" in changed:
            reinstall(repo)
        subject = git(repo, "log", "-1", "--format=%s")
        print(f"update: pulled {behind} commit(s) from {upstream}: {subject}", flush=True)
        return subject
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:  # no git, offline, ...: try later
        print(f"update: couldn't check for updates: {e}", flush=True)
        return None


def restart_command(argv: list[str] | None = None) -> list[str]:
    """The command that starts this watcher again with the same options, without a console window."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
    return [str(pyw), "-m", "lento_library", *(sys.argv[1:] if argv is None else argv)]


def restart(argv: list[str] | None = None) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(restart_command(argv), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, creationflags=flags, start_new_session=sys.platform != "win32")
