/**
 * Pitch tracking for one instrument playing one note at a time.
 *
 * YIN (de Cheveigné & Kawahara 2002) with parabolic interpolation, which gives a
 * pitch to about a cent. A frame counts as pitched when YIN's aperiodicity is low
 * and the frame is not quiet.
 */

export const SAMPLE_RATE = 22050;
export const HOP = 256; // about 11.6 ms
const WINDOW = 1024; // samples compared per lag
const FMIN = 60; // just under the cello's low C (65.4 Hz)
const FMAX = 1400;
const THRESHOLD = 0.15;
const MAX_APERIODICITY = 0.35;
const QUIET = 0.02; // relative to the loudest frame

export interface PitchTrack {
  times: Float64Array; // seconds at frame centres
  midi: Float64Array; // fractional MIDI pitch, NaN where no pitch
  rms: Float64Array; // 0..1
  onset: Float64Array; // 0..1
  hopSec: number;
  duration: number;
}

/** Plain resampling to the analysis rate, with a moving-average low-pass when going down. */
export function resample(x: Float32Array, rate: number, target = SAMPLE_RATE): Float32Array {
  if (rate === target) return x;
  let src = x;
  const ratio = rate / target;
  if (ratio > 1) {
    const k = Math.max(1, Math.round(ratio));
    src = new Float32Array(x.length);
    let acc = 0;
    for (let i = 0; i < x.length; i++) {
      acc += x[i];
      if (i >= k) acc -= x[i - k];
      src[i] = acc / Math.min(i + 1, k);
    }
  }
  const n = Math.floor(x.length / ratio);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const p = i * ratio;
    const j = Math.floor(p);
    const f = p - j;
    out[i] = src[j] * (1 - f) + (src[Math.min(j + 1, src.length - 1)] ?? 0) * f;
  }
  return out;
}

export function trackPitch(input: Float32Array, a4 = 440): PitchTrack {
  // normalise
  let peak = 0;
  for (const v of input) peak = Math.max(peak, Math.abs(v));
  if (peak < 1e-4) throw new Error("the recording is silent");
  const x = new Float32Array(input.length);
  for (let i = 0; i < input.length; i++) x[i] = input[i] / peak;

  const tauMin = Math.floor(SAMPLE_RATE / FMAX);
  const tauMax = Math.ceil(SAMPLE_RATE / FMIN);
  const span = WINDOW + tauMax + 1;
  const nFrames = Math.max(1, Math.floor(x.length / HOP) + 1);
  const times = new Float64Array(nFrames);
  const midi = new Float64Array(nFrames).fill(NaN);
  const rms = new Float64Array(nFrames);
  const d = new Float64Array(tauMax + 2);
  const frame = new Float32Array(span);

  for (let f = 0; f < nFrames; f++) {
    const centre = f * HOP;
    times[f] = centre / SAMPLE_RATE;
    const start = centre - (span >> 1);
    for (let i = 0; i < span; i++) {
      const k = start + i;
      frame[i] = k >= 0 && k < x.length ? x[k] : 0;
    }
    let e = 0;
    for (let i = 0; i < WINDOW; i++) e += frame[i] * frame[i];
    rms[f] = Math.sqrt(e / WINDOW);
    if (rms[f] < 1e-4) continue;

    // difference function and its cumulative-mean normalisation
    d[0] = 1;
    let running = 0;
    for (let tau = 1; tau <= tauMax + 1; tau++) {
      let s = 0;
      for (let i = 0; i < WINDOW; i++) {
        const diff = frame[i] - frame[i + tau];
        s += diff * diff;
      }
      running += s;
      d[tau] = running > 0 ? (s * tau) / running : 1;
    }
    let best = -1;
    for (let tau = tauMin; tau <= tauMax; tau++) {
      if (d[tau] < THRESHOLD) {
        while (tau + 1 <= tauMax && d[tau + 1] < d[tau]) tau++;
        best = tau;
        break;
      }
    }
    if (best < 0) {
      let m = Infinity;
      for (let tau = tauMin; tau <= tauMax; tau++) if (d[tau] < m) [m, best] = [d[tau], tau];
    }
    if (d[best] > MAX_APERIODICITY) continue;
    const a = d[best - 1];
    const b = d[best];
    const c = d[best + 1];
    const denom = a - 2 * b + c;
    const shift = denom !== 0 ? Math.max(-1, Math.min(1, (0.5 * (a - c)) / denom)) : 0;
    const f0 = SAMPLE_RATE / (best + shift);
    midi[f] = 69 + 12 * Math.log2(f0 / a4);
  }

  let maxRms = 0;
  for (const v of rms) maxRms = Math.max(maxRms, v);
  for (let f = 0; f < nFrames; f++) {
    rms[f] /= maxRms || 1;
    if (rms[f] < QUIET) midi[f] = NaN;
  }

  // onsets: rises in loudness (bow attacks, bow changes after a dip)
  const onset = new Float64Array(nFrames);
  for (let f = 2; f < nFrames; f++) {
    onset[f] = Math.max(0, Math.log(rms[f] + 1e-3) - Math.log(rms[f - 2] + 1e-3));
  }
  const sorted = Array.from(onset).sort((p, q) => p - q);
  const hi = sorted[Math.floor(0.99 * (sorted.length - 1))] || 1;
  for (let f = 0; f < nFrames; f++) onset[f] = Math.min(1, onset[f] / hi);

  return { times, midi, rms, onset, hopSec: HOP / SAMPLE_RATE, duration: x.length / SAMPLE_RATE };
}
