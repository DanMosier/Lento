/**
 * The PDF side of splitting, with pdf.js (Mozilla's PDF reader, the one in Firefox): page pictures for choosing
 * where each piece starts, the PDF's bookmarks, and copying a run of pages into a new PDF. pdf.js is large, so it
 * loads only when the splitter opens, and its heavy work (reading the file, decoding scans) runs in its own worker,
 * off the page. It copies pages without changing them, and it copes with the permission-locked PDFs many free
 * sheet music sites publish.
 */
import type { PDFDocumentProxy } from "pdfjs-dist";
import type { Bookmark } from "./plan";

type PdfJs = typeof import("pdfjs-dist");
let lib: Promise<PdfJs> | null = null;

function pdfjs(): Promise<PdfJs> {
  lib ??= Promise.all([import("pdfjs-dist"), import("pdfjs-dist/build/pdf.worker.min.mjs?url")])
    .then(([m, worker]) => {
      m.GlobalWorkerOptions.workerSrc = worker.default;
      return m;
    })
    .catch((e: unknown) => {
      lib = null; // offline the first time: try again next time
      throw e;
    });
  return lib;
}

export type PdfDoc = PDFDocumentProxy;

/** Opens the PDF. pdf.js takes over the bytes, so pass a copy if you still need them. */
export async function openPdf(bytes: Uint8Array): Promise<PdfDoc> {
  const m = await pdfjs();
  try {
    return await m.getDocument({ data: bytes, isEvalSupported: false }).promise;
  } catch (e) {
    if ((e as { name?: string }).name === "PasswordException") throw new Error("This PDF needs a password to open, so it can't be split here.");
    throw new Error(`Couldn't read this PDF (${(e as Error).message}).`);
  }
}

/** Draws a page into the canvas, `width` CSS pixels wide (sharp on high-density screens). */
export async function drawPage(doc: PdfDoc, pageNo: number, canvas: HTMLCanvasElement, width: number): Promise<void> {
  const page = await doc.getPage(pageNo);
  const base = page.getViewport({ scale: 1 });
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  const vp = page.getViewport({ scale: (width * dpr) / base.width });
  canvas.width = Math.round(vp.width);
  canvas.height = Math.round(vp.height);
  await page.render({ canvas, viewport: vp }).promise;
  page.cleanup();
}

/** The PDF's bookmarks (top level), with the page each points at. Empty when it has none. */
export async function bookmarks(doc: PdfDoc): Promise<Bookmark[]> {
  try {
    const outline = (await doc.getOutline()) ?? [];
    const out: Bookmark[] = [];
    for (const item of outline) {
      let dest = item.dest;
      if (typeof dest === "string") dest = await doc.getDestination(dest);
      const ref = Array.isArray(dest) ? dest[0] : null;
      if (ref == null) continue;
      const index = typeof ref === "number" ? ref : await doc.getPageIndex(ref as Parameters<PdfDoc["getPageIndex"]>[0]);
      out.push({ title: item.title ?? "", page: index + 1 });
    }
    return out;
  } catch {
    return []; // broken bookmarks are no reason not to split
  }
}

/** A new PDF of pages `start` to `end` (from 1, inclusive). */
export function extract(doc: PdfDoc, start: number, end: number): Promise<Uint8Array> {
  return doc.extractPages([{ document: null, includePages: [[start - 1, end - 1]] }]);
}
