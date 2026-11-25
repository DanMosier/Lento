/** Makes the big test score and a matching 3-minute recording, so the perf run needs no checked-in media. */

const STEPS = [36, 38, 40, 41, 43, 45, 47, 48, 50, 52, 53, 55, 57, 59, 60, 62]; // C2..D4, cello range
const NAMES = ["C", "C", "D", "D", "E", "F", "F", "G", "G", "A", "A", "B"];
const ALTER = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0];

function pitchXml(midi) {
  const pc = midi % 12;
  const oct = Math.floor(midi / 12) - 1;
  return `<pitch><step>${NAMES[pc]}</step>${ALTER[pc] ? `<alter>1</alter>` : ""}<octave>${oct}</octave></pitch>`;
}

export function midiAt(i) {
  const up = i % 30 < 15;
  return STEPS[up ? i % 15 : 15 - (i % 15)];
}

/** A cello part in 4/4 at `bpm`, quarter notes, with `measures` measures. */
export function scoreXml(measures, bpm = 120, title = "Perf test") {
  let notes = 0;
  let body = "";
  for (let m = 1; m <= measures; m++) {
    body += `<measure number="${m}">`;
    if (m === 1)
      body += `<attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>F</sign><line>4</line></clef></attributes><direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>${bpm}</per-minute></metronome></direction-type><sound tempo="${bpm}"/></direction>`;
    for (let b = 0; b < 4; b++) body += `<note>${pitchXml(midiAt(notes++))}<duration>1</duration><type>quarter</type></note>`;
    body += `</measure>`;
  }
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0"><work><work-title>${title}</work-title></work><part-list><score-part id="P1"><part-name>Violoncello</part-name></score-part></part-list><part id="P1">${body}</part></score-partwise>`;
}

/** A bowed-string-like take of the score above: 16-bit mono WAV. */
export function takeWav(measures, bpm = 120, rate = 22050) {
  const beat = 60 / bpm;
  const n = measures * 4;
  const total = Math.ceil((n * beat + 1) * rate);
  const pcm = new Int16Array(total);
  for (let i = 0; i < n; i++) {
    const f = 440 * 2 ** ((midiAt(i) - 69) / 12);
    const start = Math.round((0.5 + i * beat) * rate);
    const len = Math.round(beat * 0.92 * rate);
    for (let k = 0; k < len; k++) {
      const t = k / rate;
      const env = Math.min(1, k / (0.03 * rate)) * Math.min(1, (len - k) / (0.02 * rate));
      let v = 0;
      for (let h = 1; h <= 6; h++) v += Math.sin(2 * Math.PI * f * h * t) / h;
      pcm[start + k] = Math.round(env * v * 6000);
    }
  }
  const buf = Buffer.alloc(44 + pcm.byteLength);
  buf.write("RIFF", 0);
  buf.writeUInt32LE(36 + pcm.byteLength, 4);
  buf.write("WAVEfmt ", 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24);
  buf.writeUInt32LE(rate * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write("data", 36);
  buf.writeUInt32LE(pcm.byteLength, 40);
  Buffer.from(pcm.buffer).copy(buf, 44);
  return buf;
}
