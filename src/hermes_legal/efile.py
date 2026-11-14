"""Prepare (never file) an ordered, paginated, format-checked e-filing bundle.

Design rules:
- Checks the Verify-All citation gate across every PDF in the bundle before
  preparing output. Any unverified, not-found, or ambiguous citation blocks
  preparation.
- Never overwrites an existing output PDF or manifest file.
- Never submits or files anything; outputs a ready-to-file PDF and a JSON
  manifest with ``"filed": False``.
"""
from __future__ import annotations

import hashlib
import io
import json
import pathlib
from typing import Any

from . import citations, pdf_tools


def check_bundle_inputs(
    input_files: list[tuple[str, pathlib.Path]],
    *,
    resolver: Any = None,
    attestations: dict[str, Any] | None = None,
) -> list[dict]:
    """Format-check each PDF and run the Verify-All citation gate on its text."""
    pypdf = pdf_tools._require_pypdf()
    checked: list[dict] = []
    for rel, path in input_files:
        raw = path.read_bytes()
        try:
            reader = pypdf.PdfReader(io.BytesIO(raw))
        except Exception as exc:
            raise ValueError(f"invalid PDF {rel}: {exc}") from exc
        page_count = len(reader.pages)
        if page_count == 0:
            raise ValueError(f"PDF has zero pages: {rel}")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        gate = citations.verify_all_gate(
            text,
            resolver=resolver,
            attestations=attestations,
        )
        if not gate.allowed:
            blocked = ", ".join(gate.blocked_citations)
            raise ValueError(f"Verify-All gate blocked {rel}: {gate.message} ({blocked})")
        checked.append({
            "path": rel,
            "pages": page_count,
            "citations_checked": len(gate.results),
        })
    return checked


def build_efile_bundle(
    input_files: list[tuple[str, pathlib.Path]],
    *,
    resolver: Any = None,
    attestations: dict[str, Any] | None = None,
) -> tuple[bytes, dict]:
    """Merge ordered PDFs into one paginated bundle PDF and return ``(pdf_bytes, manifest)``."""
    pypdf = pdf_tools._require_pypdf()
    checked = check_bundle_inputs(input_files, resolver=resolver, attestations=attestations)

    writer = pypdf.PdfWriter()
    entries: list[dict] = []
    current_page = 1
    for item, (_, path) in zip(checked, input_files):
        reader = pypdf.PdfReader(io.BytesIO(path.read_bytes()))
        start_page = current_page
        for page in reader.pages:
            writer.add_page(page)
            current_page += 1
        end_page = current_page - 1
        entries.append({
            "order": len(entries) + 1,
            "path": item["path"],
            "pages": item["pages"],
            "start_page": start_page,
            "end_page": end_page,
            "citations_checked": item["citations_checked"],
        })

    buf = io.BytesIO()
    writer.write(buf)
    bundle_bytes = buf.getvalue()
    manifest = {
        "filed": False,
        "total_pages": current_page - 1,
        "bundle_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "documents": entries,
        "note": "Prepared for human review and filing. Hermes Legal never files.",
    }
    return bundle_bytes, manifest


def format_manifest_json(manifest: dict) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
