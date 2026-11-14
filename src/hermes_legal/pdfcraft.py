"""PdfCraft as the PDF engine for redaction and Bates stamping.

PdfCraft (https://github.com/storytold/pdfcraft, MIT OR Apache-2.0) is a
PDF reader and editor written in Rust. Its ``pdfcraft-cli run`` command
runs a script of JSON tool calls on one engine session. This module drives
that command and hides everything about it: callers ask for
:func:`redact` or :func:`bates` and get back verified files or an error.

Why PdfCraft rather than the standard-library writer in ``pdf_tools``:

- **Redaction keeps the document.** PdfCraft cuts the marked glyphs out of
  the page content and keeps the rest of every line in place, clears the
  covered pixels of images, and its Remove Hidden Information step drops
  metadata, attachments, comments, hidden text and layers. The
  ``pdf_tools`` rebuild keeps only the text layer.
- **Bates numbering spans a production.** ``doc_bates_multi`` numbers an
  ordered set of files as one sequence, the way a production is stamped.

Nothing here trusts PdfCraft's report on its own. Every redacted file is
re-extracted with pypdf (the ``pdf`` extra), an independent parser, and
its decoded streams are searched byte for byte; any phrase that survives
either check means no output is written. Bates outputs are re-extracted
the same way and every page must carry its label.

Files are copied into a private temporary directory that is passed to
PdfCraft as ``--root``, so the engine can read and write nothing else, and
finished files are moved into place without overwriting anything.

Locating the CLI: ``HERMES_LEGAL_PDFCRAFT`` (a path to ``pdfcraft-cli``),
else ``pdfcraft-cli`` on ``PATH``.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import zlib
from dataclasses import dataclass, field
from typing import Callable, Sequence

from . import pdf_tools

CLI_ENV = "HERMES_LEGAL_PDFCRAFT"
CLI_NAME = "pdfcraft-cli"
TIMEOUT_SECONDS = 600

#: Plain-language coverage of a PdfCraft redaction, printed by the CLI.
REDACTION_COVERAGE = (
    "covered: every occurrence PdfCraft finds is cut from the page content, with the rest "
    "of each line kept in place and covered image pixels cleared; hidden information "
    "(metadata, attachments, comments, form fields, hidden text and layers, bookmarks, "
    "links and scripts, private data) is removed; the file is rewritten in full, so no "
    "earlier revision survives; an independent re-extraction (pypdf) and a byte search of "
    "the decoded streams both found none of the phrases",
    "not covered: text that exists only inside an image (a scan with no text layer) is not "
    "found by a text search, so run OCR on scans first; review the result before producing it",
)

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


class PdfCraftError(RuntimeError):
    """PdfCraft is missing, failed, or produced output that did not verify."""


def find_cli(environ=None) -> str | None:
    """The PdfCraft CLI to run, or None when it is not installed."""
    env = os.environ if environ is None else environ
    configured = (env.get(CLI_ENV) or "").strip()
    if configured:
        return configured if pathlib.Path(configured).is_file() else None
    return shutil.which(CLI_NAME)


def available(environ=None) -> bool:
    return find_cli(environ) is not None


def _default_runner(argv: Sequence[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(list(argv), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=TIMEOUT_SECONDS, check=False)


@dataclass
class _Session:
    """One private working directory and the CLI that runs inside it."""

    cli: str
    root: pathlib.Path
    runner: Runner

    def run(self, steps: list[dict]) -> list:
        """Run ``steps`` as one script; return each step's result."""
        script = self.root / f".script-{len(list(self.root.glob('.script-*')))}.json"
        script.write_text(json.dumps(steps), encoding="utf-8")
        try:
            proc = self.runner([self.cli, "run", "--script", str(script),
                                "--root", str(self.root), "--report"])
        finally:
            script.unlink(missing_ok=True)
        try:
            report = json.loads(proc.stdout)
        except (TypeError, ValueError):
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise PdfCraftError("PdfCraft returned no report"
                                + (f": {detail[-1]}" if detail else "")) from None
        if not report.get("ok"):
            failed = next((s for s in report.get("steps", []) if s.get("status") == "error"), {})
            raise PdfCraftError(f"PdfCraft failed: {failed.get('error') or 'unknown error'}")
        return [step.get("result") for step in report.get("steps", [])]


def _session(root: pathlib.Path, cli: str | None, runner: Runner | None) -> _Session:
    found = cli or find_cli()
    if not found:
        raise PdfCraftError(
            f"PdfCraft is not installed: put {CLI_NAME} on PATH or set {CLI_ENV} to its path "
            "(https://github.com/storytold/pdfcraft/releases)")
    return _Session(found, root, runner or _default_runner)


def _first(result):
    """A step result is a list with one object per document; take the first."""
    if isinstance(result, list):
        return result[0] if result else {}
    return result or {}


def _place(built: pathlib.Path, dest: pathlib.Path) -> None:
    """Move a finished file into place; never overwrite an existing one."""
    dest = pathlib.Path(dest)
    with dest.open("xb") as handle:
        handle.write(built.read_bytes())


def _decoded_streams(data: bytes) -> bytes:
    """The file's raw bytes plus every Flate stream decoded."""
    out = [data]
    for body in re.findall(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            out.append(zlib.decompress(body))
        except zlib.error:
            try:
                out.append(zlib.decompressobj().decompress(body))
            except zlib.error:
                pass
    return b"\n".join(out)


def _byte_survivors(data: bytes, phrases: Sequence[str]) -> list[str]:
    haystack = _decoded_streams(data).lower()
    survivors = []
    for phrase in phrases:
        if not phrase:
            continue
        forms = {phrase.encode("cp1252", "replace").lower(),
                 phrase.lower().encode("utf-16-be"),
                 phrase.upper().encode("utf-16-be")}
        if any(form and form in haystack for form in forms):
            survivors.append(phrase)
    return survivors


# --------------------------------------------------------------- redaction

@dataclass
class RedactionOutcome:
    output: pathlib.Path
    marked: dict[str, int]
    hidden_removed: list[str]
    verification: pdf_tools.RedactionVerification
    byte_survivors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verification.passed and not self.byte_survivors

    def as_dict(self) -> dict:
        return {"output": str(self.output), "engine": "pdfcraft", "marked": self.marked,
                "hidden_removed": self.hidden_removed, "passed": self.passed,
                "verification": self.verification.as_dict(),
                "byte_survivors": self.byte_survivors}


def redact(source, dest, phrases: Sequence[str], *, cli: str | None = None,
           runner: Runner | None = None, case_sensitive: bool = False) -> RedactionOutcome:
    """Redact every phrase from ``source`` and write the result to ``dest``.

    Raises :class:`PdfCraftError` when PdfCraft is missing or fails, and
    returns an outcome with ``passed`` False, writing nothing, when any
    phrase survives the independent checks. ``dest`` is never overwritten.
    """
    phrases = [p for p in phrases if p and p.strip()]
    if not phrases:
        raise ValueError("redaction needs at least one phrase")
    source, dest = pathlib.Path(source), pathlib.Path(dest)
    if dest.exists():
        raise FileExistsError(f"{dest} already exists; redaction never overwrites a file")
    data = source.read_bytes()
    if not pdf_tools.is_pdf_bytes(data):
        raise ValueError("not a PDF: the input carries no %PDF- header")
    pdf_tools._require_pypdf()  # the independent check is not optional
    with tempfile.TemporaryDirectory(prefix="hermes-legal-pdfcraft-") as tmp:
        root = pathlib.Path(tmp)
        (root / "in.pdf").write_bytes(data)
        session = _session(root, cli, runner)
        # Pass 1: what is there. A mark for a phrase with no match fails the
        # whole script, and removing hidden information fails when there is
        # none, so only what exists is acted on.
        probe = [{"tool": "doc_open", "args": {"path": "in.pdf"}},
                 {"tool": "doc_hidden_info", "args": {"doc": 1}}]
        probe += [{"tool": "text_find", "args": {"doc": 1, "query": p, "limit": 100000}}
                  for p in phrases]
        results = session.run(probe)
        hidden = [c["category"] for c in _first(results[1]).get("categories", [])
                  if c.get("count")]
        marked = {p: int(_first(r).get("count", 0)) for p, r in zip(phrases, results[2:])}
        # Pass 2: mark, apply, sanitize, full rewrite.
        steps = [{"tool": "doc_open", "args": {"path": "in.pdf"}}]
        steps += [{"tool": "redact_mark",
                   "args": {"doc": 1, "find": p, "case_sensitive": case_sensitive}}
                  for p in phrases if marked[p]]
        if any(marked.values()):
            steps.append({"tool": "redact_apply", "args": {"doc": 1}})
        if hidden:
            steps.append({"tool": "doc_remove_hidden", "args": {"doc": 1}})
        steps.append({"tool": "doc_save", "args": {"doc": 1, "path": "out.pdf", "full": True}})
        session.run(steps)
        built = root / "out.pdf"
        if not built.is_file():
            raise PdfCraftError("PdfCraft reported success but wrote no file")
        output = built.read_bytes()
        verification = pdf_tools.verify_redaction(pdf_tools.extract_text_layer(output), phrases)
        survivors = _byte_survivors(output, phrases)
        outcome = RedactionOutcome(dest, marked, hidden, verification, survivors)
        if outcome.passed:
            _place(built, dest)
        return outcome


# ------------------------------------------------------------------- Bates

@dataclass
class BatesFile:
    source: pathlib.Path
    output: pathlib.Path
    first: str
    last: str
    pages: int

    def as_dict(self) -> dict:
        return {"source": str(self.source), "output": str(self.output), "pages": self.pages,
                "first": self.first, "last": self.last}


def bates(pairs: Sequence[tuple], config: pdf_tools.BatesConfig | None = None, *,
          cli: str | None = None, runner: Runner | None = None) -> list[BatesFile]:
    """Stamp one consecutive Bates sequence across ``pairs`` of (source, output).

    The sequence runs through the files in order, so the second file starts
    where the first ended. Every output page is re-extracted and must carry
    its label. All outputs are checked before any is written, and no
    existing file is overwritten.
    """
    config = config or pdf_tools.BatesConfig()
    pairs = [(pathlib.Path(s), pathlib.Path(o)) for s, o in pairs]
    if not pairs:
        raise ValueError("Bates stamping needs at least one file")
    outputs = [o.resolve() for _, o in pairs]
    if len(set(outputs)) != len(outputs):
        raise ValueError("two files would be written to the same output path")
    for _, out in pairs:
        if out.exists():
            raise FileExistsError(f"{out} already exists; stamping never overwrites a file")
    pdf_tools._require_pypdf()
    with tempfile.TemporaryDirectory(prefix="hermes-legal-pdfcraft-") as tmp:
        root = pathlib.Path(tmp)
        files = []
        for index, (src, _) in enumerate(pairs):
            data = src.read_bytes()
            if not pdf_tools.is_pdf_bytes(data):
                raise ValueError(f"not a PDF: {src}")
            (root / f"in-{index}.pdf").write_bytes(data)
            files.append({"input": f"in-{index}.pdf", "output": f"out-{index}.pdf"})
        session = _session(root, cli, runner)
        session.run([{"tool": "doc_bates_multi", "args": {
            "prefix": config.prefix, "suffix": config.suffix, "digits": config.digits,
            "start_number": config.start, "files": files}}])
        stamped, number = [], config.start
        for index, (src, out) in enumerate(pairs):
            built = root / f"out-{index}.pdf"
            if not built.is_file():
                raise PdfCraftError(f"PdfCraft wrote no stamped file for {src}")
            text = pdf_tools.extract_text_layer(built.read_bytes())
            labels = []
            for page in text.pages:
                label = pdf_tools.format_bates_label(number, config)
                if label not in page.text:
                    raise PdfCraftError(
                        f"{src}: page {page.page_number} does not carry Bates label {label}")
                labels.append(label)
                number += 1
            stamped.append(BatesFile(src, out, labels[0] if labels else "",
                                     labels[-1] if labels else "", len(labels)))
        for index, item in enumerate(stamped):
            _place(root / f"out-{index}.pdf", item.output)
        return stamped
