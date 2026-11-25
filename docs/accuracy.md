# Accuracy, export flags and orchestral scores

Measured November 2026 with homr commit `c3e75e4`, default settings, GPU.

## Measured accuracy

| Score | Pitch F1 | Pitch + timing F1 | Enforced minimum (pitch / timing) |
|---|---|---|---|
| Synthetic waltz | 100% | 100% | 99% / 99% |
| Merry-Go-Round of Life | 99.6% | 99.6% | 99% / 99% |
| Moonlight, 3rd movement | 93.7% | 89.4% | 93% / 89% |
| Rachmaninoff Concerto 2, 1st movement | 95.6% | 78.6% | 95% / 78% |
| Synthetic ensemble | 97.9% | 96.7% | 97% / 96% |

Minimums are in `tests/fixtures/baselines.json` and checked by `pytest -m homr_gpu`.

## Export flags

An export has no reference to compare with, so `quality.py` estimates the share of measures with nothing suspicious:

- measures that are empty or do not add up to the time signature
- a key signature that changes and changes back within 8 measures, or vanishes at the end
- symbols homr itself was unsure of (recorded by `homr_bridge.py`)

| Level | Rule | Meaning |
|---|---|---|
| OK | estimate 95% or more | spot-check |
| REVIEW | below 95% | check the listed measures |
| UNRELIABLE | below 80%, or instruments were merged or differ in length | do not rely on the export |

95% is the recommended baseline. Change it with `--review-below` or in the GUI. Flagged exports are still written, with
`name.quality.json` beside them.

### How far to trust it

Judged per system against the references (poor = pitch + timing F1 below 90%):

| | Systems | Poor | Poor ones flagged | Flags that were right |
|---|---|---|---|---|
| Calibration: the three smaller scores | 84 | 21 | 81% | 71% |
| Validation: the concerto, read system by system | 74 | 52 | 100% | 71% |

- The concerto result is weak evidence: 73 of its 74 systems were flagged, so it shows little about telling good from bad.
- Wrong notes in a measure that adds up are invisible. Merry-Go-Round's one wrong note is not flagged.
- homr's own probabilities are a weak signal alone (rank correlation about 0.3 with accuracy).
- The estimate is not an accuracy percentage. Four scores are too few to calibrate one.

## Full scores: reading system by system

A full score hides resting instruments, so staves come and go and homr loses track of which is which. The app then
reads one system at a time (`system_reader.py`), matches staves with instruments by their printed labels
(`instruments.py`) and joins the systems instrument by instrument (`system_merge.py`).

- **When:** only if the layout changes within a page or from page to page. Other scores take homr's own path and their
  output is unchanged, byte for byte.
- **Without labels:** if fewer than half of the systems have a label, homr's own result is kept and flagged.
- **Scans:** labels come from the PDF's text, or from OCR if it has none.
- **Uncertain staves:** never guessed. They are kept in parts named "Unplaced staff" and listed in the flag.

| Concerto | Before | Now |
|---|---|---|
| Pitch F1 | 28.1% | 95.6% |
| Pitch F1, in the right instrument | not possible | 95.5% |
| Pitch + timing F1, in the right instrument | not possible | 78.6% |
| Measures (374 expected) | 1,433 | 374 |

All 19 instruments were found in order and all staves placed. The code was developed against this score, so it is not
an independent result. The synthetic ensemble (other engraver, English labels, 11 instruments) was made afterwards and
nothing was tuned on it: 97.1% / 95.9% in the right instrument, one piano staff unplaced and flagged. Ten concerto
pages as a tilted 200 dpi scan: all instruments found by OCR, one staff unplaced and flagged; its notes were not scored.

Known limits:

- homr reads tenor clefs as alto clefs, a third too high (Tromboni I II 27%, Violoncello 87%). Unusual clefs are
  flagged, not corrected.
- Rhythm of dense piano writing (Piano: pitch 95%, pitch + timing 64%).
- Transposing instruments are written as printed, without a transposition, so they play back at the wrong pitch.
- If every page shows the same number of staves but for different instruments, the change is not noticed.
- For full scores the estimate is the share of notes in consistent measures. It has not been calibrated: the concerto
  gets 77%, the ensemble 96%.
