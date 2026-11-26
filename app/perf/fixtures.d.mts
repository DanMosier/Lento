/** Types for fixtures.mjs, so the unit tests can use its test PDF. */
export function midiAt(i: number): number;
export function scoreXml(measures: number, bpm?: number, title?: string): string;
export function takeWav(measures: number, bpm?: number, rate?: number): Uint8Array;
export function sheetPdf(pages: number, titled?: number[]): Uint8Array;
