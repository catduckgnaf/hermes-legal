# Document editing: DOCX redlines, PDF Bates plans, and true redaction

This page describes what works today in the Python package. It is narrower
than the full editing stack in [Desktop](desktop.md): the visual editors
(ONLYOFFICE and LibreOffice), OCR, and rendered PDF writing are separate
build items, and nothing on this page claims them.

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

## Fidelity corpus (`hermes_legal.docx_fixtures`)

Generated, byte-identical DOCX cases for the features a round trip through
Word or LibreOffice must survive: plain paragraphs, numbering
(`w:numPr` with a numbering part), footnotes (a footnote reference with a
footnotes part), tables (`w:tbl` between paragraphs), and pre-existing
tracked changes. The tests build the corpus, check each package is a valid
zip with parseable document XML, and check that a table survives a redline
of the paragraphs around it. Rendering comparison in the visual editors is
still a separate item; this corpus proves structure, not pixels.

## PDF: Bates plan and redaction verification (`hermes_legal.pdf_tools`)

- `plan_bates_stamps(page_count, config)`: the exact Bates label for every
  page (prefix, zero-padded number, suffix), unique and consecutive. This
  is a plan for a writer step to render; `legal bates-plan` prints the plan
  and says so — it does not stamp a PDF.
- True redaction works on the extracted text layer (`DocumentText`, one
  string per page). `locate_redactions` finds every occurrence,
  `apply_redaction_to_text` removes the text itself (a black rectangle over
  surviving text is not redaction), and `verify_redaction` re-checks the
  result three ways — exact, case-insensitive, and whitespace-normalized —
  so a phrase split across a line break still fails verification.
  `legal redact-verify <text-file> <phrase>...` runs that check on an
  extracted text file and exits nonzero when anything remains.
- Reading a real PDF's text layer (`extract_text_layer`) uses the optional
  `pdf` extra, `pypdf`. The plan and verification logic never needs it.
