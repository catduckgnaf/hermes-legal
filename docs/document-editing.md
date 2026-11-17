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

### Manual release gate: open a redline in Word and LibreOffice

Automated tests prove the XML and, where `soffice` is installed, a
LibreOffice headless conversion. CI runners do not install LibreOffice,
so that test skips there, and no runner has Microsoft Word. Before a
release that changes `docx_edit.py` or `docx_fixtures.py`, a person runs
this gate and records the result in the release pull request:

1. Build a redline with `legal redline` from a real Word-authored
   document (one saved by Word itself, with numbering, a footnote and a
   table), not only from the generated corpus.
2. Open the output in Microsoft Word. It must open with no repair
   prompt. On the Review tab, every change appears as a tracked
   insertion or deletion under the AI author name, and Accept All then
   Reject All (on a second copy) each give the expected text.
3. Open the same output in LibreOffice Writer. Edit > Track Changes >
   Manage lists the same changes, and accept and reject both work.
4. Check that numbering, the footnote and the table are intact in both
   programs.
5. Run `uv run python -m pytest -q -rs tests/test_libreoffice_fidelity.py`
   on a machine with LibreOffice and confirm it ran rather than skipped.

Record: the Word and LibreOffice versions, the operating system, and
pass or fail for each step. A failure blocks the release.

## PDF: Bates stamping and true redaction (PdfCraft, `hermes_legal.pdfcraft`)

Redaction and Bates stamping run on [PdfCraft](https://github.com/storytold/pdfcraft),
an open-source PDF engine written in Rust (MIT OR Apache-2.0). Hermes Legal
drives its `pdfcraft-cli run` command; it does not bundle it. Install a
PdfCraft release and put `pdfcraft-cli` on `PATH`, or set
`HERMES_LEGAL_PDFCRAFT` to its path. On Windows the CLI ships inside the
`windows-x64-portable.zip` release asset. `legal doctor` reports whether it
was found. Real PDFs also need the optional `pdf` extra (`pypdf`), which is
the independent checker below.

- **Redaction.** `legal redact <input.pdf> <phrase>... -o <output.pdf>`
  finds each phrase with PdfCraft, marks and applies the redactions, removes
  hidden information (metadata, attachments, comments, form fields, hidden
  text and layers, bookmarks, links and scripts, private data) and rewrites
  the whole file, so no earlier revision survives. PdfCraft cuts the marked
  glyphs out of the page content and keeps the rest of each line in place,
  and clears the covered pixels of images, so the document keeps its
  layout, fonts and graphics.
  - Nothing is trusted on PdfCraft's word. The output is re-extracted with
    pypdf, a separate parser, and checked three ways (exact,
    case-insensitive, whitespace-normalized), and the decoded streams are
    searched byte for byte. If any phrase survives either check, no output
    is written and the command exits 1.
  - A phrase PdfCraft does not find is reported by name; nothing is
    removed for it. A phrase pypdf still finds after redaction blocks the
    output, so a phrase one parser sees and the other does not cannot pass.
  - Not covered: text that exists only inside an image (a scan with no
    text layer) is not found by a text search. Run OCR on scans first, and
    review the result before producing it.
  - The output is never overwritten, and PdfCraft works in a private
    temporary folder passed as `--root`, so it can read and write nothing
    else.
- **Bates stamping.** `legal bates-stamp <a.pdf> [<b.pdf> ...] --out-dir <folder>`
  (or `-o <output.pdf>` for one file) stamps one consecutive sequence
  across the files in order, the way a production is numbered: if `a.pdf`
  has two pages, `b.pdf` starts at the third label. Options: `--prefix`,
  `--suffix`, `--start`, `--digits`. Every output page is re-extracted and
  must carry its label, all outputs are checked before any is written, and
  no existing file is overwritten. `--engine auto` (the default) uses
  PdfCraft when it is installed and otherwise the pypdf overlay
  (`stamp_pdf`), which adds the label without touching page content.
- `plan_bates_stamps(page_count, config)`: the exact Bates label for every
  page, unique and consecutive. `legal bates-plan` prints the plan only and
  says so.
- **Text-only rebuild (fallback).** `legal redact ... --engine rebuild`
  works without PdfCraft: `redact_pdf` extracts the text layer, removes the
  phrases and writes a brand-new PDF from the remaining text, verified the
  same way. It keeps only the text: layout, fonts, images and graphics are
  lost, which is why it is not the default.
- `legal redact-verify <file> <phrase>...` re-checks any PDF (or a plain
  text file, saying plainly that no PDF was checked). For a PDF it runs
  the whole-file audit (`pdf_tools.audit_redacted_pdf`), which fails
  closed. The file passes only when all of these hold:
  - no phrase in the text layer re-extracted from the file;
  - no phrase in the raw bytes or in any Flate stream of any revision,
    in any spelling a PDF can use (literal, UTF-16, hex string);
  - no phrase in any stream of the newest revision as pypdf decodes it
    (XMP metadata, embedded attachments, other filters);
  - no phrase in any string value (document information, annotation
    contents, form field values, bookmarks, file names);
  - the file holds one saved revision. A file with incremental-save
    history fails even when no phrase is found, because earlier page
    content stays recoverable and a phrase drawn in pieces there cannot
    be searched for; `legal redact` writes a new file with no history;
  - the file is not encrypted and its structure can be read.

  Images, annotations, attachments, form fields and metadata that are
  present are counted and printed as notes. Text that exists only as
  pixels in an image is not searched, because no OCR is run, and the
  output says so. The `redact --engine rebuild` output is held to the
  same audit before anything is written.

## Still remaining

- OCR for scanned documents (Tesseract): not built. Tesseract is not
  installed in the build environment, and wrapping it honestly also
  needs a page rasterizer; it stays an open item on the document issue.
- Visual DOCX editing via ONLYOFFICE: a desktop build item, not part of
  the Python package.
- Opening a redline in real Microsoft Word: a manual release gate, as
  stated above.
