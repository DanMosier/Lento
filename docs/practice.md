# Practice feedback (`lento-practice`)

Compares a recording of you playing with its MusicXML score and reports, note by note, how far each note was from the
written pitch (in cents), whether it came early or late, and which notes were missed or wrong. It is tuned for cello but
works for any instrument that plays one note at a time.

## Install and run

```powershell
uv pip install -e ".[practice]"
.venv\Scripts\lento-practice.exe analyze "C:\scores\etude.musicxml" "C:\takes\etude-take1.wav"
```

The report goes to a folder next to the recording (`etude-take1_feedback\`, or `--out`):

| File | What it is |
|---|---|
| `summary.md` | Tempo, counts, the three spots most worth looping, and a table of every note that needs attention |
| `etude.feedback.musicxml` | The score with notes colored and labelled. Open it in MuseScore. |
| `notes.csv` | One row per note, for a spreadsheet |
| `report.json` | Everything, for later tools (progress history, the practice list) |

Colors: green in tune, amber slightly off, red out of tune or wrong note, purple missed, blue "the score may be wrong
here", grey the second note of a double stop (not checked). The label under a note shows cents (`+18`), the note heard
(`Eb3?`), `miss`, `early` or `late`.

Options: `--measures 12-20` if you want to say which measures you played (otherwise they are found), `--part` for a score
with several parts (the cello part is picked by default), `--a4 442` for your tuning pitch, `--pitch` and `--timing`
(`strict`, `standard` or `relaxed`, set separately: in tune within 5, 10 or 20 cents; flagged beyond 60, 100 or 160 ms),
or exact values with `--in-tune`, `--slightly-off` and `--timing-ms`.

## Recording tips

- Any recording app works. WAV or FLAC is best; MP3 works.
- Tune first. If you tune to 442, pass `--a4 442`; the summary suggests a value when you are consistently sharp or flat.
- Don't play the backing track out loud while recording: the analyzer would hear it. Use headphones.
- A few measures to a page at a time gives the most useful feedback.

## How it works

1. `lento_core.score` reads the part into notes with beats and seconds (ties merged, double stops grouped).
2. pYIN finds where there is a pitch; YIN with interpolation gives the pitch to about a cent.
3. A dynamic programme lines the pitch track up with the notes in order, at whatever tempo you played. The recording may
   start and stop anywhere in the score. A second pass adds the rhythm: notes heard far from where the matched notes
   say they should be cost extra, so a passage that matches no written pitch still lines up.
4. Runs of the same pitch (repeated notes) are split where the rhythm and the bow-change onsets agree.
5. Each note's pitch is the median of its steady middle, which skips the bow attack and averages out vibrato. Timing is
   measured against a tempo line through the neighbouring two measures, so gradual slowing down is reported once in the
   summary, not against every note.
6. Four or more notes in a row all off by the same interval are flagged "score may be wrong" instead of counted as your
   mistakes. homr can read a tenor clef as alto, which moves every note by a third.

## Limits (first version)

- Tested on synthetic cello-like recordings (`tests/practice_synth.py`), including vibrato, bow noise, room echo,
  slowing down and planted mistakes. Not yet tested on real cello recordings.
- Double stops: only one of the two notes is measured.
- Repeats are read once, as written.
- Analysis runs after the take, not live.
