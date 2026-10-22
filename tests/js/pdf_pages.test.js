// Build brief 24, E (decision 17): two PDFs on one task each show their own page images. The files list names each
// page's folder (the PDF's stem, or its whole name when two PDFs share a stem); a task from before has one flat folder.
import { test } from "node:test";
import assert from "node:assert/strict";
import { pdfShots } from "../../static/app.js";

const page = (folder, n) => ({ root: "media/pages", kind: "image", folder, path: `media/pages/t/${folder ? `${folder}/` : ""}page-${n}.png` });

test("each PDF shows its own pages, never the other's", () => {
  const files = [{ root: "media/in", kind: "pdf", name: "menu.pdf" }, page("menu", 1), page("menu", 2), page("prices", 1)];
  assert.deepEqual(pdfShots({ name: "menu.pdf" }, files).map((f) => f.path), ["media/pages/t/menu/page-1.png", "media/pages/t/menu/page-2.png"]);
  assert.deepEqual(pdfShots({ name: "prices.pdf" }, files).map((f) => f.path), ["media/pages/t/prices/page-1.png"]);
  assert.deepEqual(pdfShots({ name: "other.pdf" }, files), []);
});

test("a folder by the whole name wins, and a task from before shows its flat pages", () => {
  const clash = [page("menu.pdf", 1), page("menu.PDF", 1)];
  assert.deepEqual(pdfShots({ name: "menu.PDF" }, clash).map((f) => f.folder), ["menu.PDF"]);
  const flat = [page(null, 1), page(null, 2)];
  assert.equal(pdfShots({ name: "old.pdf" }, flat).length, 2);
});
