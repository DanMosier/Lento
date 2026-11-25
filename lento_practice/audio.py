"""Load a recording and track its pitch."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050
HOP = 256  # about 11.6 ms per frame
FRAME = 2048  # about 93 ms, more than two periods of the cello's low C
FMIN = 60.0  # just under C2 (65.4 Hz)
FMAX = 1400.0  # above the cello's practical top


@dataclass
class PitchTrack:
    times: np.ndarray  # seconds, frame centres
    midi: np.ndarray  # fractional MIDI pitch, NaN where no pitch
    voiced_prob: np.ndarray
    rms: np.ndarray  # loudness per frame, 0..1 relative to the loudest frame
    onset: np.ndarray  # onset strength per frame, 0..1
    duration: float

    @property
    def hop_sec(self) -> float:
        return HOP / SAMPLE_RATE


def load_audio(path: str | Path) -> np.ndarray:
    import librosa

    y, _ = librosa.load(str(path), sr=SAMPLE_RATE, mono=True)
    if y.size == 0:
        raise ValueError(f"{path} has no audio")
    peak = float(np.max(np.abs(y)))
    if peak < 1e-4:
        raise ValueError(f"{path} is silent")
    return y / peak


def track_pitch(y: np.ndarray, a4: float = 440.0) -> PitchTrack:
    """pYIN pitch tracking, in MIDI numbers relative to the given A4."""
    import librosa

    f0, voiced, prob = librosa.pyin(
        y,
        fmin=FMIN,
        fmax=FMAX,
        sr=SAMPLE_RATE,
        frame_length=FRAME,
        hop_length=HOP,
        center=True,
    )
    # pYIN's pitch comes in 10-cent steps, too coarse for intonation. YIN with
    # parabolic interpolation is continuous; use it wherever it agrees with pYIN.
    fine = librosa.yin(y, fmin=FMIN, fmax=FMAX, sr=SAMPLE_RATE, frame_length=FRAME, hop_length=HOP, center=True)
    fine = fine[: len(f0)]
    ok = voiced & np.isfinite(f0)
    close = ok & (np.abs(1200.0 * np.log2(np.where(ok, fine, 1.0) / np.where(ok, f0, 1.0))) < 30.0)
    f = np.where(close, fine, f0)
    midi = np.full(f0.shape, np.nan)
    midi[ok] = 69.0 + 12.0 * np.log2(f[ok] / a4)

    n = len(f0)
    rms = librosa.feature.rms(y=y, frame_length=FRAME, hop_length=HOP, center=True)[0][:n]
    rms = rms / max(float(rms.max()), 1e-9)
    onset = librosa.onset.onset_strength(y=y, sr=SAMPLE_RATE, hop_length=HOP, center=True)[:n]
    onset = np.pad(onset, (0, n - len(onset)))
    hi = float(np.percentile(onset, 99)) or 1.0
    onset = np.clip(onset / hi, 0.0, 1.0)

    # quiet frames are not notes, whatever pYIN says
    quiet = rms < 0.02
    midi[quiet] = np.nan
    times = librosa.frames_to_time(np.arange(n), sr=SAMPLE_RATE, hop_length=HOP)
    return PitchTrack(times, midi, np.nan_to_num(prob), rms, onset, len(y) / SAMPLE_RATE)
