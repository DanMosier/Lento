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

/**
 * A PDF of `pages` pages that look a little like sheet music (a title on some, then staves of lines and note heads),
 * drawn as vectors, for the PDF splitter. Built by hand so the tests need no PDF library or checked-in score.
 * `titled` lists the pages that start a piece; each gets a bookmark, as an anthology's table of contents would.
 */
export function sheetPdf(pages, titled = []) {
  const objs = []; // object number - 1 -> body
  const add = (body) => objs.push(body) && objs.length;
  const catalog = add(""); // filled in below
  const pagesObj = add("");
  const font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
  const kids = [];
  for (let p = 1; p <= pages; p++) {
    let s = "";
    let top = 760;
    const start = titled.indexOf(p);
    if (start >= 0) {
      s += `BT /F1 22 Tf 180 740 Td (Piece ${start + 1}) Tj ET\n`;
      top = 680;
    }
    for (let staff = 0; staff < 9 && top - staff * 72 > 60; staff++) {
      const y0 = top - staff * 72;
      for (let l = 0; l < 5; l++) s += `40 ${y0 - l * 6} m 572 ${y0 - l * 6} l S\n`;
      for (let n = 0; n < 16; n++) s += `${60 + n * 32} ${y0 - 12 + ((n * 7 + p) % 9) * 3} 5 4 re f\n`;
    }
    s += `BT /F1 9 Tf 300 30 Td (${p}) Tj ET\n`;
    const content = add(`<< /Length ${s.length} >>\nstream\n${s}endstream`);
    kids.push(add(`<< /Type /Page /Parent ${pagesObj} 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 ${font} 0 R >> >> /Contents ${content} 0 R >>`));
  }
  let outlines = "";
  if (titled.length) {
    const outlineObj = add("");
    const first = objs.length + 1;
    titled.forEach((page, i) => {
      const prev = i ? ` /Prev ${first + i - 1} 0 R` : "";
      const next = i < titled.length - 1 ? ` /Next ${first + i + 1} 0 R` : "";
      add(`<< /Title (Piece ${i + 1}) /Parent ${outlineObj} 0 R /Dest [${kids[page - 1]} 0 R /Fit]${prev}${next} >>`);
    });
    objs[outlineObj - 1] = `<< /Type /Outlines /First ${first} 0 R /Last ${first + titled.length - 1} 0 R /Count ${titled.length} >>`;
    outlines = ` /Outlines ${outlineObj} 0 R`;
  }
  objs[catalog - 1] = `<< /Type /Catalog /Pages ${pagesObj} 0 R${outlines} >>`;
  objs[pagesObj - 1] = `<< /Type /Pages /Kids [${kids.map((k) => `${k} 0 R`).join(" ")}] /Count ${pages} >>`;
  let out = "%PDF-1.4\n";
  const offsets = [];
  objs.forEach((body, i) => {
    offsets.push(out.length);
    out += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")}`;
  out += `trailer\n<< /Size ${objs.length + 1} /Root ${catalog} 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}
