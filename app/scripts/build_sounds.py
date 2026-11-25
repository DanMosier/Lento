"""Builds the app's instrument sound packs from VS Chamber Orchestra: Community Edition (CC0).

For each instrument it reads the library's SFZ mapping, takes one recording per sampled note (VSCO samples
about every third semitone; the app pitch-shifts the notes in between), trims it, evens out its loudness,
bakes a crossfaded loop into sustained instruments so notes can be held as long as the score says, and
joins the notes into one compressed Opus file per velocity layer:

    public/sounds/<instrument>-<layer>.ogg     ("f" is the light pack; "p" is the extra soft layer for "full")
    public/sounds/index.json                   where each note sits in those files

Usage (needs ffmpeg with libopus, and numpy):
    git clone --filter=blob:none --no-checkout https://github.com/sgossner/VSCO-2-CE vsco
    git -C vsco fetch --filter=blob:none origin SFZ
    python scripts/build_sounds.py --vsco vsco
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

import numpy as np

RATE = 48000
GAP = 0.06  # silence between notes in a pack, seconds

# id: (SFZ file, kind). "sus" notes are looped; "decay" notes ring out and fade.
INSTRUMENTS = {
    "cello": ("CelloEnsSusVib.sfz", "sus"),
    "violin": ("SViolinVib.sfz", "sus"),
    "viola": ("ViolaEnsSusVib.sfz", "sus"),
    "contrabass": ("ContrabassSusVB.sfz", "sus"),
    "flute": ("FluteSusVib.sfz", "sus"),
    "oboe": ("OboeSusVib.sfz", "sus"),
    "clarinet": ("ClarinetSus.sfz", "sus"),
    "bassoon": ("BassoonSus.sfz", "sus"),
    "horn": ("FHornSus.sfz", "sus"),
    "trumpet": ("TrumpetSus.sfz", "sus"),
    "trombone": ("TromboneSus.sfz", "sus"),
    "tuba": ("TubaSus.sfz", "sus"),
    "piano": ("UprightPiano.sfz", "decay"),
    "harp": ("Harp.sfz", "decay"),
    "timpani": ("Timpani.sfz", "decay"),
}
SUS_LEN, LOOP_START, XFADE = 2.4, 0.9, 0.35
DECAY_LEN, FADE = 3.2, 0.8
LAYERS = {"f": 90, "p": 45}  # the velocity each layer is chosen at


def parse_sfz(text: str) -> tuple[str, list[dict]]:
    """Regions with their group and global opcodes applied. Returns (default_path, regions)."""
    text = re.sub(r"//[^\n]*", "", text)
    default_path = ""
    scopes: dict[str, dict] = {"global": {}, "group": {}}
    regions: list[dict] = []
    current: dict | None = None
    for tok in re.split(r"(<\w+>)", text):
        tok = tok.strip()
        if not tok:
            continue
        m = re.fullmatch(r"<(\w+)>", tok)
        if m:
            kind = m.group(1)
            if kind == "region":
                current = {**scopes["global"], **scopes["group"]}
                regions.append(current)
            elif kind in ("group", "global"):
                if kind == "global":
                    scopes["group"] = {}
                scopes[kind] = {}
                current = scopes[kind]
            else:
                current = {}
                scopes[kind] = current
            continue
        if current is None:
            continue
        # opcode=value pairs; sample= may contain spaces up to the next opcode
        for k, v in re.findall(r"(\w+)=(.*?)(?=\s+\w+=|$)", tok, flags=re.S):
            current[k] = v.strip()
            if k == "default_path":
                default_path = v.strip()
    return default_path.replace("\\", "/"), regions


def pick_layer(regions: list[dict], vel: int) -> list[dict]:
    """One region per key range, from the velocity layer that plays at `vel`, first round robin."""
    chosen: dict[tuple, dict] = {}
    for r in regions:
        lo, hi = int(r.get("lovel", 0)), int(r.get("hivel", 127))
        if not lo <= vel <= hi or int(r.get("seq_position", 1)) != 1:
            continue
        key = int(r.get("pitch_keycenter", r.get("key", 60)))
        lk, hk = int(r.get("lokey", r.get("key", key))), int(r.get("hikey", r.get("key", key)))
        chosen.setdefault((lk, hk), {**r, "_key": key, "_lo": lk, "_hi": hk})
    return sorted(chosen.values(), key=lambda r: r["_key"])


def load_wav(vsco: Path, path: str) -> np.ndarray:
    """Mono float samples at RATE, from the checkout on disk or straight from git."""
    f = vsco / path
    data = f.read_bytes() if f.is_file() else subprocess.run(["git", "-C", str(vsco), "show", f"master:{path}"], capture_output=True, check=True).stdout
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "pipe:0", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "pipe:1"], input=data, capture_output=True, check=True
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def prepare(x: np.ndarray, kind: str) -> tuple[np.ndarray, float | None, float | None]:
    """Trim, level and (for sustained notes) bake a seamless loop. Returns (samples, loopStart, loopEnd) in seconds."""
    peak = float(np.max(np.abs(x))) or 1.0
    start = int(np.argmax(np.abs(x) > 0.03 * peak))
    x = x[max(0, start - int(0.004 * RATE)) :]
    if kind == "sus":
        n = min(len(x), int(SUS_LEN * RATE))
        x = x[:n].copy()
        ls, xf = int(min(LOOP_START, 0.4 * n / RATE) * RATE), int(min(XFADE, 0.25 * n / RATE) * RATE)
        le = n - int(0.01 * RATE)
        ramp = np.linspace(0, 1, xf, dtype=np.float32)
        # the end of the loop fades into what comes just before the loop start, so the jump back is seamless
        x[le - xf : le] = x[le - xf : le] * (1 - ramp) + x[ls - xf : ls] * ramp
        body = x[int(0.15 * RATE) : le]
        loop = (ls / RATE, le / RATE)
    else:
        n = min(len(x), int(DECAY_LEN * RATE))
        x = x[:n].copy()
        f = min(int(FADE * RATE), n // 3)
        x[n - f :] *= np.linspace(1, 0, f, dtype=np.float32) ** 2
        body = x[: int(0.5 * RATE)]
        loop = (None, None)
    rms = float(np.sqrt(np.mean(body**2))) or 1e-4
    gain = min(10 ** (-18 / 20) / rms, 0.9 / (float(np.max(np.abs(x))) or 1))
    return x * gain, *loop


def encode(x: np.ndarray, out: Path, kbps: int) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", "pipe:0",
         "-c:a", "libopus", "-b:a", f"{kbps}k", "-application", "audio", str(out)],
        input=x.astype(np.float32).tobytes(), check=True,
    )


def build(vsco: Path, out: Path, kbps: int, only: list[str] | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    index = {
        "format": "lento-sounds",
        "version": 1,
        "source": "VS Chamber Orchestra: Community Edition (CC0 1.0), https://github.com/sgossner/VSCO-2-CE",
        "instruments": {},
    }
    old = out / "index.json"
    if only and old.is_file():  # rebuilding some instruments keeps the others
        index["instruments"] = json.loads(old.read_text(encoding="utf-8")).get("instruments", {})
    for inst, (sfz, kind) in INSTRUMENTS.items():
        if only and inst not in only:
            continue
        text = subprocess.run(["git", "-C", str(vsco), "show", f"FETCH_HEAD:{sfz}"], capture_output=True, text=True).stdout
        if not text:
            text = (vsco / sfz).read_text(encoding="utf-8", errors="replace")
        base, regions = parse_sfz(text)
        entry: dict = {"loop": kind == "sus", "layers": {}}
        seen: set[str] = set()
        for layer, vel in LAYERS.items():
            picked = pick_layer(regions, vel)
            samples = tuple(r["sample"] for r in picked)
            if not picked or "|".join(samples) in seen:  # no separate soft layer: "full" is the same as "light"
                continue
            seen.add("|".join(samples))
            chunks, notes, t = [], [], 0.0
            for r in picked:
                x, ls, le = prepare(load_wav(vsco, base + r["sample"].replace("\\", "/")), kind)
                note = {"key": r["_key"], "lo": r["_lo"], "hi": r["_hi"], "start": round(t, 4), "end": round(t + len(x) / RATE, 4)}
                if r.get("tune"):
                    note["tune"] = int(float(r["tune"]))  # cents
                if ls is not None:
                    note["loopStart"], note["loopEnd"] = round(t + ls, 4), round(t + le, 4)
                notes.append(note)
                chunks += [x, np.zeros(int(GAP * RATE), np.float32)]
                t += len(x) / RATE + GAP
            name = f"{inst}-{layer}.ogg"
            encode(np.concatenate(chunks), out / name, kbps)
            entry["layers"][layer] = {"file": name, "vel": vel, "bytes": (out / name).stat().st_size, "notes": notes}
            print(f"{name}: {len(notes)} notes, {t:.1f} s, {(out / name).stat().st_size / 1024:.0f} KB", flush=True)
        index["instruments"][inst] = entry
    (out / "index.json").write_text(json.dumps(index, separators=(",", ":")) + "\n", encoding="utf-8")
    return index


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vsco", required=True, type=Path, help="VSCO-2-CE checkout (master, with the SFZ branch fetched)")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "public" / "sounds")
    ap.add_argument("--kbps", type=int, default=48)
    ap.add_argument("--only", nargs="*", help="instrument ids to build (default: all)")
    a = ap.parse_args()
    build(a.vsco, a.out, a.kbps, a.only)
