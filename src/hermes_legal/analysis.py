"""Deterministic matter analysis: chronology building and intake summaries.

Both functions are pure-reading over on-disk matter documents and never call a
model or write to the database. Every extracted item cites its source file and
segment index so a human can verify it against the underlying record.
"""
from __future__ import annotations

import pathlib
import re
from typing import Callable

from . import citations, deadlines, matters

_AMOUNT_RE = re.compile(r"\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?(?:\s*(?:million|billion|thousand|k|m))?\b", re.I)
_FIELD_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /_-]{1,40}):\s+(.+?)\s*$")
_EXPECTED_INTAKE_GROUPS = (
    ("client", ("client", "client_name", "name")),
    ("opposing_party", ("opposing_party", "adverse_party", "defendant", "respondent")),
    ("matter_type", ("matter_type", "claim", "case_type", "subject")),
    ("jurisdiction", ("jurisdiction", "court", "venue")),
)


def _iter_target_records(
    conn,
    matter_id: int,
    relative_path: str | None,
    resolve_file: Callable[[int, str], pathlib.Path],
) -> list[dict]:
    if relative_path is not None:
        resolved = resolve_file(matter_id, relative_path)
        return [{"relative_path": relative_path, "path": str(resolved)}]
    return matters.list_document_records(conn, matter_id)


def build_chronology(
    conn,
    matter_id: int,
    *,
    relative_path: str | None = None,
    limit: int = 100,
    resolve_file: Callable[[int, str], pathlib.Path],
    segment_reader: Callable[[pathlib.Path], tuple[str, list[str]]],
) -> dict:
    """Build a dated chronology from one document or all readable documents in a matter."""
    entries: list[dict] = []
    unreadable: list[str] = []
    seen: set[tuple[str, str, int, str]] = set()

    for record in _iter_target_records(conn, matter_id, relative_path, resolve_file):
        rel = record["relative_path"]
        try:
            unit, segments = segment_reader(pathlib.Path(record["path"]))
        except Exception:
            unreadable.append(rel)
            continue
        for index, segment in enumerate(segments):
            for candidate in deadlines.extract_candidates(segment):
                if candidate.kind != "explicit_date" or candidate.due_date is None:
                    continue
                iso_date = candidate.due_date.isoformat()
                key = (iso_date, rel, index, candidate.excerpt)
                if key in seen:
                    continue
                seen.add(key)
                entries.append({
                    "date": iso_date,
                    "raw_date": candidate.raw,
                    "source": rel,
                    "unit": unit,
                    "index": index,
                    "citation": f"{rel} ({unit} {index + 1})",
                    "event": candidate.excerpt,
                })

    entries.sort(key=lambda item: (item["date"], item["source"], item["index"]))
    total_found = len(entries)
    if limit is not None:
        entries = entries[:limit]
    return {
        "matter_id": matter_id,
        "entries": entries,
        "total_found": total_found,
        "unreadable_files": unreadable,
    }


def _normalize_field_key(raw_key: str) -> str:
    return re.sub(r"[\s/-]+", "_", raw_key.strip().lower()).strip("_")


def build_intake_summary(
    conn,
    matter_id: int,
    *,
    relative_path: str | None = None,
    resolve_file: Callable[[int, str], pathlib.Path],
    segment_reader: Callable[[pathlib.Path], tuple[str, list[str]]],
) -> dict:
    """Summarize an intake form or matter folder into a structured matter summary."""
    matter = matters.get_matter(conn, matter_id)
    documents: list[dict] = []
    unreadable: list[str] = []
    fields: dict[str, dict] = {}
    dates: list[dict] = []
    seen_dates: set[tuple[str, str, int]] = set()
    amounts: list[dict] = []
    seen_amounts: set[tuple[str, str, int]] = set()
    citations_count = 0

    for record in _iter_target_records(conn, matter_id, relative_path, resolve_file):
        rel = record["relative_path"]
        try:
            unit, segments = segment_reader(pathlib.Path(record["path"]))
        except Exception:
            unreadable.append(rel)
            continue
        documents.append({"path": rel, "unit": unit, "segments": len(segments)})
        for index, segment in enumerate(segments):
            for line in segment.splitlines():
                match = _FIELD_RE.match(line)
                if match:
                    norm_key = _normalize_field_key(match.group(1))
                    if norm_key and norm_key not in fields:
                        fields[norm_key] = {
                            "label": match.group(1).strip(),
                            "value": match.group(2).strip(),
                            "source": rel,
                            "unit": unit,
                            "index": index,
                        }
            for candidate in deadlines.extract_candidates(segment):
                if candidate.kind == "explicit_date" and candidate.due_date is not None:
                    iso_date = candidate.due_date.isoformat()
                    dkey = (iso_date, rel, index)
                    if dkey not in seen_dates:
                        seen_dates.add(dkey)
                        dates.append({
                            "date": iso_date,
                            "raw": candidate.raw,
                            "source": rel,
                            "unit": unit,
                            "index": index,
                        })
            for amt_match in _AMOUNT_RE.finditer(segment):
                amount_text = " ".join(amt_match.group(0).split())
                akey = (amount_text, rel, index)
                if akey not in seen_amounts:
                    seen_amounts.add(akey)
                    amounts.append({
                        "amount": amount_text,
                        "source": rel,
                        "unit": unit,
                        "index": index,
                        "excerpt": " ".join(segment.split())[:200],
                    })
            citations_count += len(citations.extract_citations(segment, include_unrecognized=True))

    dates.sort(key=lambda item: (item["date"], item["source"], item["index"]))
    missing_fields = [
        group_name
        for group_name, aliases in _EXPECTED_INTAKE_GROUPS
        if not any(alias in fields for alias in aliases)
    ]
    return {
        "matter": {
            "id": matter["id"],
            "name": matter["name"],
            "folder": matter["folder"],
            "privacy_ceiling": matter["privacy_ceiling"],
            "status": matter["status"],
        },
        "documents": documents,
        "unreadable_files": unreadable,
        "fields": fields,
        "dates": dates,
        "amounts": amounts,
        "citations_found": citations_count,
        "missing_intake_fields": missing_fields,
    }
