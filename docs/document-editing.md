# Document editing: DOCX redlines, PDF Bates stamping, and true redaction

This page describes what works today in the Python package. It is narrower
than the full editing stack in [Desktop](desktop.md): the visual editor
(ONLYOFFICE), OCR, and opening files in real Microsoft Word are separate
items, and nothing on this page claims them.

## DOCX compare and redline (`hermes_legal.docx_edit`)

Standard library only — a DOCX is a zip, and the module patches
`word/document.xml` inside it.

- `compare_docx(old, new)` / `compare_paragraphs(old, new)`: a deterministic,
  paragraph-level diff. Same input, same change list, no model involved.
- `build_redline(original, revised)`: a new DOCX carrying real `w:ins` /
  `w:del` track changes, including tracked paragraph marks, so a replaced
  paragraph shows as a deletion directly followed by an insertion. Every
  change is authored `hermes-legal (AI - unverified)` with a timestamp, and
  the document settings enable revision tracking. The file opens in Word
  and LibreOffice as native track changes for a human to accept or reject.
- Accepting a built redline yields exactly the revised paragraphs and
  rejecting it yields exactly the original ones; the tests pin that round
  trip (`accept_all_text` / `reject_all_text`).
- Scope limit, stated plainly: the builder works on top-level body
  paragraphs. Tables and other block elements are preserved unchanged in
  place, and text inside a table cell is not redlined.

From the command line:

```sh
legal doc-compare original.docx revised.docx --json
legal doc-redline original.docx revised.docx -o redline.docx
```

## Fidelity corpus and the LibreOffice gate (`hermes_legal.docx_fixtures`)

Generated, byte-identical DOCX cases for the features a round trip through
Word or LibreOffice must survive: plain paragraphs, numbering
(`w:numPr` with a numbering part), footnotes (a footnote reference with a
footnotes part), tables (`w:tbl` between paragraphs), pre-existing
tracked changes, and a Word-authored-style case (`word_style`) that
reproduces the patterns real Word files carry — `mc:Ignorable` namespace
declarations, `w14:paraId` attributes, `w:rsidR` revision identifiers,
and `w:ins` / `w:del` elements with `w:id`, author, and date.

The LibreOffice fidelity gate (`tests/test_libreoffice_fidelity.py`)
converts a built redline and the Word-style fixture with LibreOffice
headless and checks the conversion succeeds and the inserted text
survives as document content. It runs wherever `soffice` is installed
and skips cleanly where it is not. The gate immediately earned its keep:
LibreOffice refused to load every generated DOCX because the package
parts (`[Content_Types].xml` and the `.rels` files) were serialized with
an invented `ns0:` namespace prefix instead of the default namespace;
those parts are now written in the default-namespace form, with a
regression test that needs no LibreOffice to run. Opening a redline in
real Microsoft Word remains a manual release gate — Word is not
available in the build environment, and this page does not claim it.

## PDF: Bates stamping and true redaction (`hermes_legal.pdf_tools`)

- `plan_bates_stamps(page_count, config)`: the exact Bates label for every
  page (prefix, zero-padded number, suffix), unique and consecutive.
  `legal bates-plan` prints the plan only and says so.
- `stamp_pdf(pdf_bytes, config)`: a stamped copy of a real PDF, with the
  planned label rendered on every page. The source pages are preserved
  (content, images, metadata); only the overlay label is added.
  `legal bates-stamp <input.pdf> -o <output.pdf> --prefix ACME-` writes
  it and refuses to overwrite an existing file. Tests prove the label is
  present on re-extraction from the output bytes and that the page count
  and original content survive.
- True redaction is a rebuild, not a cover-up. `redact_pdf(pdf_bytes,
  phrases)` extracts the text layer, removes every occurrence of the
  phrases, and writes a brand-new PDF from the redacted text only, then
  verifies the result on text re-extracted from the rebuilt bytes (plus
  a raw-bytes check). `legal redact <input.pdf> <phrase>... -o
  <output.pdf>` writes nothing when verification fails. What the rebuild
  covers, stated plainly in the CLI output as well:
  - Covered: target phrases removed from the text layer and verified
    absent on re-extraction and in the raw bytes; document metadata
    cleared (no info dictionary or XMP is written); incremental-save
    history dropped, because the output is a new file; annotations,
    attachments, and form fields are not carried into the rebuild.
  - Not covered: text embedded in images was never in the text layer
    and no OCR check is run, so image content is not verified; the
    rebuild keeps only the text layer, so original layout, fonts,
    images, and graphics are not preserved.
- Verification on its own still works as before: `verify_redaction`
  re-checks a text layer three ways — exact, case-insensitive, and
  whitespace-normalized — and `legal redact-verify <file> <phrase>...`
  runs it, verifying a real PDF on text re-extracted from its bytes and
  saying plainly when no PDF was checked.
- Reading and writing real PDFs uses the optional `pdf` extra, `pypdf`.
  The plan and verification logic never needs it, and the raw PDF writer
  used for overlays, fixtures, and the redaction rebuild is standard
  library only.

## Still remaining

- OCR for scanned documents (Tesseract): not built. Tesseract is not
  installed in the build environment, and wrapping it honestly also
  needs a page rasterizer; it stays an open item on the document issue.
- Visual DOCX editing via ONLYOFFICE: a desktop build item, not part of
  the Python package.
- Opening a redline in real Microsoft Word: a manual release gate, as
  stated above.
