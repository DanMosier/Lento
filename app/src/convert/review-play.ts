/**
 * Listening to a converted score in the Review window, to hear wrong notes before approving it. Every part plays
 * with its instrument's sound, using the same player as Practice (core/player).
 *
 * Loaded only the first time Play is pressed, and the score is read into notes only then, so opening and paging
 * through reviews costs nothing extra. Sound packs download in the background; until one arrives that part plays
 * with the synth.
 */
import { sharedAudio } from "../core/app";
import { timed } from "../core/perf";
import { partInstrument, Player } from "../core/player";
import { roomOut } from "../core/room";
import { listParts, parseScore, type Score } from "../core/score";
import { SoundBank } from "../core/sounds";

let player: Player | null = null;
let sounds: SoundBank | null = null;
let parts: Score[] = [];
let partsOf: string | null = null; // the score text the parts were read from, so a fix makes them read again

/** Every part of the score that has notes, as the player wants them. */
export function readParts(xml: string): Score[] {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  const all: Score[] = [];
  for (const p of listParts(doc)) {
    try {
      const s = parseScore(doc, p.id);
      if (s.notes.length) all.push(s);
    } catch {
      /* a part that can't be read stays silent */
    }
  }
  return all;
}

/**
 * Starts playing `xml` from `fromMeasure` (1 = the first measure in the file) at `tempoFactor`. Resolves with the
 * number of measures, or throws if the score has nothing to play. `onEnd` runs when it reaches the end.
 */
export async function play(xml: string, fromMeasure: number, tempoFactor: number, onEnd: () => void): Promise<number> {
  return timed("review-play", async () => {
    if (!player) {
      const ctx = sharedAudio();
      sounds = new SoundBank(ctx);
      player = new Player(ctx, roomOut(ctx), sounds);
    }
    if (partsOf !== xml) {
      parts = readParts(xml);
      partsOf = xml;
      const insts = parts.map(partInstrument);
      setTimeout(() => void sounds?.want(insts), 0);
    }
    if (!parts.length) throw new Error("This score has no notes to play.");
    const last = parts[0].measures.length - 1;
    const from = Math.max(0, Math.min(last, fromMeasure - 1));
    player.onEnd = onEnd;
    await player.play({ parts, fromMeasure: from, toMeasure: last, tempoFactor, countIn: false, loop: false, click: 0 });
    return last + 1;
  });
}

export function stop(): void {
  player?.stop();
}

/** The measure being heard now (its number as printed), or null when not playing. */
export function nowMeasure(): string | null {
  const beat = player?.currentBeat() ?? null;
  if (beat == null || !parts.length) return null;
  const s = parts[0];
  let i = 0;
  while (i + 1 < s.measureStarts.length && s.measureStarts[i + 1] <= beat + 1e-6) i++;
  return s.measures[i] ?? null;
}

export function isPlaying(): boolean {
  return !!player?.playing;
}
