"""Multi-instrument open-source VST audio synthesizer and interactive Windows MusicXML playback engine."""

from __future__ import annotations

import array
import ctypes
import math
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

from .models import InstrumentPart, ParsedScore
from .vst_catalog import VST_BY_ID, recommend_vst_for_instrument

try:
    import winsound
except ImportError:  # pragma: no cover
    winsound = None  # type: ignore[assignment]


def midi_to_freq(midi_note: int) -> float:
    """Convert a MIDI note number (0-127, 69=A4=440Hz) to frequency in Hz."""
    return 440.0 * (2.0 ** ((midi_note - 69.0) / 12.0))


def _get_part_synthesis_profile(part: InstrumentPart) -> dict[str, Any]:
    """Retrieve the acoustic synthesis parameters for a part's assigned open-source VST."""
    spec = VST_BY_ID.get(part.assigned_vst_id) or recommend_vst_for_instrument(part.part_name, part.midi_program)
    return dict(spec.synthesis_profile)


def synthesize_score_to_wav(
    score: ParsedScore,
    output_wav_path: Path,
    sample_rate: int = 22050,
    tempo_override_bpm: float | None = None,
    max_duration_sec: float = 180.0,
) -> Path:
    """Synthesize a ParsedScore into a stereo 16-bit PCM WAV using each part's assigned open-source VST profile."""
    tempo_scale = 1.0
    if tempo_override_bpm and tempo_override_bpm > 20.0 and score.tempo_bpm > 0:
        tempo_scale = score.tempo_bpm / tempo_override_bpm

    total_sec = min(max_duration_sec, max(1.0, score.total_duration_sec * tempo_scale + 0.6))
    num_samples = int(total_sec * sample_rate)

    left_buf = array.array("f", [0.0]) * num_samples
    right_buf = array.array("f", [0.0]) * num_samples

    any_solo = any(p.solo for p in score.parts)
    active_parts = [
        p for p in score.parts if not p.muted and (not any_solo or p.solo) and p.volume > 0.01
    ]

    two_pi = 2.0 * math.pi
    num_parts = max(1, len(active_parts))

    for p_idx, part in enumerate(active_parts):
        profile = _get_part_synthesis_profile(part)
        harmonics: list[tuple[float, float]] = profile.get("harmonics", [(1.0, 1.0), (2.0, 0.4), (3.0, 0.2)])
        attack_sec = float(profile.get("attack_sec", 0.02))
        decay_rate = float(profile.get("decay_rate", 1.5))
        sustain_level = float(profile.get("sustain_level", 0.5))
        release_sec = float(profile.get("release_sec", 0.15))
        vib_hz = float(profile.get("vibrato_hz", 0.0))
        vib_depth = float(profile.get("vibrato_depth", 0.0))
        mode = str(profile.get("mode", "piano"))

        # Pan each part slightly across the stereo stage
        if num_parts == 1:
            pan = 0.0
        else:
            pan = -0.35 + (0.70 * p_idx / (num_parts - 1))
        gain_l = math.sqrt(0.5 * (1.0 - pan)) * part.volume
        gain_r = math.sqrt(0.5 * (1.0 + pan)) * part.volume

        # Pre-normalize harmonic weights
        harm_sum = sum(amp for _, amp in harmonics) or 1.0
        norm_harmonics = [(mult, amp / harm_sum) for mult, amp in harmonics]

        for note in part.playable_notes:
            start_t = note.start_sec * tempo_scale
            if start_t >= total_sec:
                continue
            dur_t = max(0.05, note.duration_sec * tempo_scale)
            end_t = min(total_sec, start_t + dur_t + release_sec)

            start_idx = max(0, int(start_t * sample_rate))
            end_idx = min(num_samples, int(end_t * sample_rate))
            if end_idx <= start_idx:
                continue

            base_freq = midi_to_freq(note.pitch_midi)
            vel_gain = (max(20, min(127, note.velocity)) / 127.0) * 0.35

            # Limit high-frequency aliasing
            nyquist = sample_rate * 0.45
            valid_harmonics = [(m, a) for m, a in norm_harmonics if base_freq * m < nyquist]
            if not valid_harmonics:
                valid_harmonics = [(1.0, 1.0)]

            inv_sr = 1.0 / sample_rate
            att_inv = 1.0 / max(0.002, attack_sec)
            rel_inv = 1.0 / max(0.01, release_sec)

            for i in range(start_idx, end_idx):
                t = (i - start_idx) * inv_sr
                # ADSR + exponential decay envelope
                if t < attack_sec:
                    env = t * att_inv
                elif t < dur_t:
                    decay_env = math.exp(-decay_rate * (t - attack_sec))
                    env = sustain_level + (1.0 - sustain_level) * decay_env
                else:
                    rel_t = t - dur_t
                    end_hold_env = sustain_level + (1.0 - sustain_level) * math.exp(
                        -decay_rate * max(0.0, dur_t - attack_sec)
                    )
                    env = end_hold_env * max(0.0, 1.0 - rel_t * rel_inv)

                if env <= 0.0005:
                    continue

                # Optional vibrato modulation for strings/winds/brass/choir
                freq_inst = base_freq
                if vib_depth > 0.0 and t > attack_sec * 1.2:
                    freq_inst = base_freq * (1.0 + vib_depth * math.sin(two_pi * vib_hz * t))

                # Percussive pitch drop for timpani/percussion
                if mode == "percussion":
                    freq_inst = base_freq * (1.0 + 0.18 * math.exp(-18.0 * t))

                phase = two_pi * freq_inst * t
                sample_val = 0.0
                for mult, amp in valid_harmonics:
                    # Slight harmonic damping over time for plucked/piano modes
                    if mode in ("piano", "plucked") and mult > 1.5:
                        h_damp = math.exp(-0.7 * (mult - 1.0) * t)
                        sample_val += amp * h_damp * math.sin(phase * mult)
                    else:
                        sample_val += amp * math.sin(phase * mult)

                val = sample_val * env * vel_gain
                left_buf[i] += val * gain_l
                right_buf[i] += val * gain_r

    # Soft limiter & normalize to 16-bit stereo PCM
    peak = 0.0
    for i in range(num_samples):
        al = abs(left_buf[i])
        ar = abs(right_buf[i])
        if al > peak:
            peak = al
        if ar > peak:
            peak = ar

    master_scale = min(1.35, 0.90 / peak) if peak > 0.001 else 1.0
    pcm_data = array.array("h", [0]) * (num_samples * 2)

    for i in range(num_samples):
        l_int = int(max(-32767.0, min(32767.0, left_buf[i] * master_scale * 32767.0)))
        r_int = int(max(-32767.0, min(32767.0, right_buf[i] * master_scale * 32767.0)))
        idx2 = i * 2
        pcm_data[idx2] = l_int
        pcm_data[idx2 + 1] = r_int

    output_wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_wav_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data.tobytes())

    return output_wav_path


class MusicXMLAudioPlayer:
    """Windows multimedia audio player with Play, Pause, Stop, Seek, and live cursor tracking."""

    def __init__(self) -> None:
        self._alias = "pdf2mxml_preview"
        self._current_wav: Path | None = None
        self._is_playing: bool = False
        self._is_paused: bool = False
        self._duration_sec: float = 0.0
        self._start_wall_time: float = 0.0
        self._pause_position_sec: float = 0.0
        self._use_mci: bool = hasattr(ctypes, "windll")

    def _mci_send(self, command: str) -> tuple[int, str]:
        if not self._use_mci:
            return -1, ""
        buf = ctypes.create_unicode_buffer(256)
        err = ctypes.windll.winmm.mciSendStringW(command, buf, 255, 0)
        return int(err), buf.value

    @property
    def is_playing(self) -> bool:
        return self._is_playing and not self._is_paused

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def duration_sec(self) -> float:
        return self._duration_sec

    def load_and_render_score(
        self,
        score: ParsedScore,
        tempo_override_bpm: float | None = None,
    ) -> Path:
        """Synthesize the score with its assigned open-source VST profiles to a temporary WAV file."""
        self.stop()
        tmp_dir = Path(tempfile.gettempdir()) / "pdf_to_musicxml_audio"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        wav_path = tmp_dir / f"preview_{int(time.time() * 1000) % 1000000}.wav"
        synthesize_score_to_wav(
            score=score,
            output_wav_path=wav_path,
            tempo_override_bpm=tempo_override_bpm,
        )
        self._current_wav = wav_path

        tempo_scale = 1.0
        if tempo_override_bpm and tempo_override_bpm > 20.0 and score.tempo_bpm > 0:
            tempo_scale = score.tempo_bpm / tempo_override_bpm
        self._duration_sec = max(1.0, score.total_duration_sec * tempo_scale)
        self._pause_position_sec = 0.0
        return wav_path

    def play(self, start_sec: float | None = None) -> None:
        """Start or resume playback from `start_sec` (or current paused position)."""
        if not self._current_wav or not self._current_wav.is_file():
            return

        pos_sec = start_sec if start_sec is not None else (self._pause_position_sec if self._is_paused else 0.0)
        pos_sec = max(0.0, min(self._duration_sec, pos_sec))
        pos_ms = int(pos_sec * 1000)

        if self._use_mci:
            self._mci_send(f"close {self._alias}")
            err, _ = self._mci_send(f'open "{self._current_wav}" type waveaudio alias {self._alias}')
            if err == 0:
                self._mci_send(f"set {self._alias} time format milliseconds")
                self._mci_send(f"play {self._alias} from {pos_ms}")
                self._is_playing = True
                self._is_paused = False
                self._start_wall_time = time.perf_counter() - pos_sec
                self._pause_position_sec = pos_sec
                return

        # Fallback to winsound async playback
        if winsound is not None:
            winsound.PlaySound(str(self._current_wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
        self._is_playing = True
        self._is_paused = False
        self._start_wall_time = time.perf_counter() - pos_sec
        self._pause_position_sec = pos_sec

    def pause(self) -> None:
        """Pause active playback while preserving position."""
        if not self._is_playing or self._is_paused:
            return
        self._pause_position_sec = self.get_position_sec()
        if self._use_mci:
            self._mci_send(f"pause {self._alias}")
        elif winsound is not None:
            winsound.PlaySound(None, winsound.SND_PURGE)
        self._is_paused = True

    def stop(self) -> None:
        """Stop playback and reset playhead to 0.0s."""
        if self._use_mci:
            self._mci_send(f"stop {self._alias}")
            self._mci_send(f"close {self._alias}")
        if winsound is not None:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
        self._is_playing = False
        self._is_paused = False
        self._pause_position_sec = 0.0

    def seek(self, position_sec: float) -> None:
        """Seek to a specific position in seconds."""
        clamped = max(0.0, min(self._duration_sec, position_sec))
        self._pause_position_sec = clamped
        if self._is_playing and not self._is_paused:
            self.play(start_sec=clamped)

    def get_position_sec(self) -> float:
        """Return the current playhead position in seconds."""
        if not self._is_playing:
            return 0.0
        if self._is_paused:
            return self._pause_position_sec

        if self._use_mci:
            err, val = self._mci_send(f"status {self._alias} position")
            if err == 0 and val.strip().isdigit():
                pos = int(val.strip()) / 1000.0
                if pos >= self._duration_sec - 0.05:
                    self.stop()
                    return self._duration_sec
                return pos

        elapsed = time.perf_counter() - self._start_wall_time
        if elapsed >= self._duration_sec:
            self.stop()
            return self._duration_sec
        return max(0.0, elapsed)
