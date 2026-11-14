"""Playbook review and clause library.

Playbooks are open, editable Markdown files -- not a vendor black box.
A reviewer edits a playbook file and the next review changes with no
code change. This module is stdlib only: it defines a small
Markdown / YAML-ish format (see ``docs/playbooks.md``), parses it,
splits contract text into clauses, and checks the clauses against
the rules in the playbook.

The behavior behind the ``legal_playbook_review`` tool lives here:
:func:`legal_playbook_review` returns findings tied to clauses.
It changes nothing. Proposed language in a finding is a suggestion
only; it becomes a redline only through the approval-gated
``legal_doc_redline`` tool.

Playbook format (summary)
-------------------------
::

    # Playbook: Mutual NDA
    id: nda
    name: Mutual NDA
    version: 1
    description: Positions for reviewing a mutual non-disclosure agreement.

    ## Rules

    ### require-confidentiality-definition
    title: Definition of Confidential Information is required
    kind: required
    severity: high
    topic: confidentiality
    patterns: confidential information
    must_contain: oral; written
    rationale: Without a definition the duty has no clear scope.
    fallback: Confidential Information means non-public information ...

    ### forbid-perpetuity
    title: Confidentiality must not be perpetual
    kind: forbidden
    severity: medium
    topic: confidentiality
    patterns: in perpetuity; perpetual
    rationale: Perpetual duties are outside the approved position.
    fallback: The duty survives for three years after disclosure.

    ### governing-law-position
    title: Governing law position
    kind: fallback
    severity: medium
    topic: governing law
    patterns: governing law; governed by
    preferred: Delaware
    acceptable: New York; California
    rationale: Delaware is preferred; New York or California are acceptable fallbacks.
    fallback: This Agreement is governed by the laws of the State of Delaware.

    ## Clause library

    ### confidentiality-definition
    title: Definition of Confidential Information
    language: Confidential Information means ...
    fallback: If the counterparty will not accept the preferred language, ...

Parsing rules:

* Header metadata and rule / library fields are ``key: value`` lines.
* List values (``patterns``, ``must_contain``, ``preferred``,
  ``acceptable``, ``keywords``) are separated by semicolons, so a
  phrase may itself contain commas.
* A pattern wrapped in slashes (``/regex/``) is a regular expression;
  every other pattern is a case-insensitive substring.
* Prose outside a ``###`` block is ignored, so a playbook can carry
  human notes without breaking the parser.
* Matching is negation-aware: a mention that is negated in its own
  sentence (``no indemnification``, ``shall not indemnify``,
  ``in no event will a party indemnify``, ``indemnification is not
  provided``) does not count as a match. A required clause whose only
  mention is negated is reported missing, tied to that clause.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Clause",
    "Finding",
    "LibraryClause",
    "Playbook",
    "PlaybookError",
    "ReviewResult",
    "Rule",
    "find_playbooks",
    "legal_playbook_review",
    "load_playbook",
    "parse_playbook",
    "playbook_review",
    "review_contract",
    "split_clauses",
]


class PlaybookError(ValueError):
    """Raised when a playbook file cannot be parsed."""


_LIST_KEYS = {"patterns", "pattern", "must_contain", "preferred", "acceptable", "keywords", "search", "search_terms"}
_KIND_ALIASES = {
    "required": "required",
    "required_clause": "required",
    "required-clause": "required",
    "forbidden": "forbidden",
    "forbidden_language": "forbidden",
    "forbidden-language": "forbidden",
    "fallback": "fallback",
    "fallback_position": "fallback",
    "fallback-position": "fallback",
}


def _norm_key(key: str) -> str:
    return key.strip().lower().replace("-", "_")


def _split_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def _parse_fields(lines: list[str]) -> dict:
    fields: dict = {}
    last_key: str | None = None
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- ") and last_key in _LIST_KEYS:
            fields[last_key].append(stripped[2:].strip())
            continue
        if ":" not in stripped:
            # Prose inside a block is ignored.
            continue
        key, _, value = stripped.partition(":")
        key = _norm_key(key)
        value = value.strip()
        last_key = key
        if key in _LIST_KEYS:
            fields[key] = _split_list(value) if value else []
        else:
            # Allow a long value to continue in a simple way: last wins
            # for scalars is intentional and documented.
            fields[key] = value
    return fields


@dataclass(frozen=True)
class Rule:
    id: str
    title: str = ""
    kind: str = "required"
    severity: str = "medium"
    topic: str = ""
    patterns: tuple[str, ...] = ()
    must_contain: tuple[str, ...] = ()
    preferred: tuple[str, ...] = ()
    acceptable: tuple[str, ...] = ()
    rationale: str = ""
    fallback: str = ""

    @property
    def search_terms(self) -> tuple[str, ...]:
        if self.patterns:
            return self.patterns
        if self.topic:
            return (self.topic,)
        return ()


@dataclass(frozen=True)
class LibraryClause:
    id: str
    title: str = ""
    language: str = ""
    fallback: str = ""
    notes: str = ""


@dataclass(frozen=True)
class Playbook:
    id: str
    name: str = ""
    version: str = ""
    description: str = ""
    rules: tuple[Rule, ...] = ()
    library: tuple[LibraryClause, ...] = ()
    source: str = ""

    def library_by_id(self) -> dict[str, LibraryClause]:
        return {c.id: c for c in self.library}


@dataclass(frozen=True)
class Clause:
    index: int
    heading: str = ""
    number: str = ""
    text: str = ""
    body: str = ""

    def to_dict(self) -> dict:
        return {"index": self.index, "heading": self.heading, "number": self.number, "text": self.text}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    kind: str
    severity: str
    status: str
    topic: str = ""
    clause_index: int | None = None
    clause_heading: str = ""
    clause_number: str = ""
    message: str = ""
    rationale: str = ""
    excerpt: str = ""
    fallback: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind,
            "severity": self.severity,
            "status": self.status,
            "topic": self.topic,
            "clause_index": self.clause_index,
            "clause_heading": self.clause_heading,
            "clause_number": self.clause_number,
            "message": self.message,
            "rationale": self.rationale,
            "excerpt": self.excerpt,
            "fallback": self.fallback,
        }


@dataclass(frozen=True)
class ReviewResult:
    playbook_id: str
    playbook_name: str = ""
    findings: tuple[Finding, ...] = ()
    clause_count: int = 0
    rules_checked: int = 0
    clauses: tuple[Clause, ...] = field(default=())

    def to_dict(self) -> dict:
        return {
            "playbook_id": self.playbook_id,
            "playbook_name": self.playbook_name,
            "clause_count": self.clause_count,
            "rules_checked": self.rules_checked,
            "findings": [f.to_dict() for f in self.findings],
            "summary": {
                "total": len(self.findings),
                "missing": sum(1 for f in self.findings if f.status == "missing"),
                "forbidden": sum(1 for f in self.findings if f.status == "forbidden"),
                "incomplete": sum(1 for f in self.findings if f.status == "incomplete"),
                "deviation": sum(1 for f in self.findings if f.status == "deviation"),
                "fallback_acceptable": sum(1 for f in self.findings if f.status == "fallback_acceptable"),
            },
        }


# ---------------------------------------------------------------------------
# Playbook parsing
# ---------------------------------------------------------------------------

def parse_playbook(text: str, source: str = "") -> Playbook:
    lines = text.splitlines()
    meta: dict = {}
    rules: list[Rule] = []
    library: list[LibraryClause] = []
    section = ""  # "", "rules", "library"
    current_id: str | None = None
    current_lines: list[str] = []

    def flush():
        nonlocal current_id, current_lines
        if current_id is None:
            return
        fields = _parse_fields(current_lines)
        if section == "rules":
            kind_raw = str(fields.get("kind") or fields.get("type") or "required").strip().lower()
            kind = _KIND_ALIASES.get(kind_raw)
            if kind is None:
                raise PlaybookError(f"playbook {source or '<text>'}: rule {current_id!r} has unknown kind {kind_raw!r}")
            patterns = tuple(fields.get("patterns") or fields.get("pattern") or [])
            for term in (*patterns, *(fields.get("must_contain") or [])):
                if len(term) >= 2 and term.startswith("/") and term.endswith("/"):
                    try:
                        re.compile(term[1:-1])
                    except re.error as exc:
                        # A rule that can never match reads as a clean review.
                        raise PlaybookError(
                            f"playbook {source or '<text>'}: rule {current_id!r} "
                            f"has an invalid pattern {term!r}: {exc}"
                        ) from exc
            rules.append(Rule(
                id=current_id,
                title=str(fields.get("title") or ""),
                kind=kind,
                severity=str(fields.get("severity") or "medium").strip().lower(),
                topic=str(fields.get("topic") or ""),
                patterns=patterns,
                must_contain=tuple(fields.get("must_contain") or []),
                preferred=tuple(fields.get("preferred") or []),
                acceptable=tuple(fields.get("acceptable") or []),
                rationale=str(fields.get("rationale") or ""),
                fallback=str(fields.get("fallback") or ""),
            ))
        elif section == "library":
            library.append(LibraryClause(
                id=current_id,
                title=str(fields.get("title") or ""),
                language=str(fields.get("language") or fields.get("text") or ""),
                fallback=str(fields.get("fallback") or ""),
                notes=str(fields.get("notes") or ""),
            ))
        current_id = None
        current_lines = []

    for raw in lines:
        stripped = raw.strip()
        h2 = re.match(r"^##\s+(.+?)\s*$", stripped)
        h3 = re.match(r"^###\s+(.+?)\s*$", stripped)
        h1 = re.match(r"^#\s+(.+?)\s*$", stripped)
        if h2:
            flush()
            heading = h2.group(1).strip().lower()
            if "rule" in heading:
                section = "rules"
            elif "library" in heading or "clause" in heading:
                section = "library"
            else:
                section = ""
            continue
        if h3 and section in {"rules", "library"}:
            flush()
            current_id = h3.group(1).strip()
            current_lines = []
            continue
        if h1 and section == "":
            # Title line: keep any "Playbook: X" as a name hint.
            title = h1.group(1).strip()
            if title.lower().startswith("playbook:"):
                meta.setdefault("name", title.split(":", 1)[1].strip())
            continue
        if current_id is not None:
            current_lines.append(raw)
        elif section == "" and ":" in stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition(":")
            key_norm = _norm_key(key)
            if key_norm in {"id", "name", "version", "description"}:
                meta[key_norm] = value.strip()
    flush()

    playbook_id = str(meta.get("id") or "").strip()
    if not playbook_id:
        raise PlaybookError(f"playbook {source or '<text>'}: missing required 'id:' in the header")
    if not rules:
        raise PlaybookError(f"playbook {source or '<text>'}: no rules found under a '## Rules' section")
    return Playbook(
        id=playbook_id,
        name=str(meta.get("name") or playbook_id),
        version=str(meta.get("version") or ""),
        description=str(meta.get("description") or ""),
        rules=tuple(rules),
        library=tuple(library),
        source=source,
    )


def load_playbook(path) -> Playbook:
    p = Path(path)
    return parse_playbook(p.read_text(encoding="utf-8"), source=str(p))


def find_playbooks(directory) -> list[Path]:
    root = Path(directory)
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*.md") if "demo-contract" not in p.name and "demo_contract" not in p.name)


# ---------------------------------------------------------------------------
# Clause splitting
# ---------------------------------------------------------------------------

_MD_HEADING = re.compile(r"^#{2,6}\s+(.+?)\s*$")
_SECTION_HEADING = re.compile(r"^(Section|Article|Clause)\s+(\d+|[IVXLCDM]+)\.?\s*[:.\-]?\s*(.*?)\s*$", re.IGNORECASE)
_NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+([A-Z][A-Za-z0-9 ,&()'/\-]{2,90})\s*$")


def _heading_for(line: str) -> tuple[str, str] | None:
    """Return (number, heading) if the line is a clause heading."""
    stripped = line.strip()
    m = _MD_HEADING.match(stripped)
    if m:
        inner = m.group(1).strip()
        num = _NUMBERED_HEADING.match(inner)
        if num:
            return num.group(1), inner
        return "", inner
    m = _SECTION_HEADING.match(stripped)
    if m:
        number = m.group(2)
        title = m.group(3).strip()
        return number, (f"{m.group(1).title()} {number} {title}".strip())
    m = _NUMBERED_HEADING.match(stripped)
    if m:
        # Avoid treating a short numbered list item as a heading: the
        # title must be at least two words or end without a period and
        # the line must be short (headings are, bodies are not).
        if len(stripped) <= 100:
            return m.group(1), stripped
    return None


def split_clauses(text: str) -> list[Clause]:
    lines = text.splitlines()
    starts: list[tuple[int, str, str]] = []  # (line_index, number, heading)
    for i, line in enumerate(lines):
        found = _heading_for(line)
        if found is not None:
            starts.append((i, found[0], found[1]))

    clauses: list[Clause] = []
    if len(starts) >= 2:
        for pos, (line_idx, number, heading) in enumerate(starts):
            end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
            chunk = "\n".join(lines[line_idx:end]).strip()
            body_lines = lines[line_idx + 1:end]
            clauses.append(Clause(
                index=len(clauses), heading=heading, number=number,
                text=chunk, body="\n".join(body_lines).strip(),
            ))
        # Any preamble before the first heading is kept as clause 0 only
        # if it has real content beyond a document title.
        first_line = starts[0][0]
        preamble = "\n".join(lines[:first_line]).strip()
        if preamble and len(preamble.split()) > 12:
            clauses.insert(0, Clause(index=0, heading="Preamble", number="", text=preamble, body=preamble))
            clauses = [Clause(index=i, heading=c.heading, number=c.number, text=c.text, body=c.body) for i, c in enumerate(clauses)]
        return clauses

    # Fallback: split on blank lines into paragraphs.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    for para in paragraphs:
        first = para.splitlines()[0].strip().lstrip("#").strip()
        heading = first[:80] if len(first) <= 80 else first[:77] + "..."
        clauses.append(Clause(index=len(clauses), heading=heading, number="", text=para, body=para))
    return clauses


# ---------------------------------------------------------------------------
# Rule checking
# ---------------------------------------------------------------------------

# Negation cues. A cue before a match counts only inside the same
# sentence segment and within a short window, so a positive mention in
# a later sentence of the same clause is not poisoned by an earlier
# negated one. A cue after a match counts only in a short list of
# post-posed forms ("is not provided", ": none", "is excluded").
_NEGATION_BEFORE_RE = re.compile(
    r"\b(?:no|not|never|none|nor|without|excludes?|excluding)\b"
    r"|\bother\s+than\b|n['\u2019]t\b",
    re.IGNORECASE,
)
_NEGATION_AFTER_RE = re.compile(
    r"\b(?:is|are|was|were|shall|will|does|do|did)\s+not\b"
    r"|\bnot\s+(?:provided|included|covered|required|applicable)\b"
    r"|:\s*none\b|\bexcluded\b|\bomitted\b",
    re.IGNORECASE,
)
_SENTENCE_BREAKS = ".!?;\n"


def _match_spans(text: str, pattern: str) -> list[tuple[int, int]]:
    pat = pattern.strip()
    if not pat:
        return []
    if len(pat) >= 2 and pat.startswith("/") and pat.endswith("/"):
        try:
            return [(m.start(), m.end()) for m in re.finditer(pat[1:-1], text, re.IGNORECASE)]
        except re.error:
            return []
    spans: list[tuple[int, int]] = []
    haystack = text.lower()
    needle = pat.lower()
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return spans
        spans.append((idx, idx + len(needle)))
        start = idx + max(len(needle), 1)


def _is_negated(text: str, start: int, end: int) -> bool:
    if text[max(0, start - 4):start].lower() in {"non-", "no-"}:
        return True
    seg_start = max((text.rfind(ch, 0, start) for ch in _SENTENCE_BREAKS), default=-1) + 1
    before = text[max(seg_start, start - 80):start]
    if _NEGATION_BEFORE_RE.search(before):
        return True
    seg_ends = [pos for ch in _SENTENCE_BREAKS if (pos := text.find(ch, end)) >= 0]
    seg_end = min(seg_ends) if seg_ends else len(text)
    after = text[end:min(seg_end, end + 60)]
    return _NEGATION_AFTER_RE.search(after) is not None


def _matches(text: str, pattern: str) -> bool:
    """True when ``pattern`` has at least one non-negated mention."""
    return any(not _is_negated(text, s, e) for s, e in _match_spans(text, pattern))


def _any_match(text: str, patterns) -> bool:
    return any(_matches(text, p) for p in patterns)


def _any_mention(text: str, patterns) -> bool:
    return any(_match_spans(text, p) for p in patterns)


def _first_match(text: str, patterns) -> str | None:
    for pattern in patterns:
        if _matches(text, pattern):
            return pattern
    return None


def _body_text(clause: Clause) -> str:
    """Clause content without its heading line.

    Satisfaction is judged on what a clause says, not on its title:
    a clause headed "Indemnification" whose body says there is none
    must not satisfy an indemnification rule on the heading alone.
    Paragraph-split clauses have no separate heading field: when a
    paragraph's first line is itself a heading, that line is dropped
    here for the same reason.
    """
    body = clause.body.strip()
    if body and body != clause.text.strip():
        return body
    text = (body or clause.text).strip()
    lines = text.splitlines()
    if len(lines) > 1 and _heading_for(lines[0]) is not None:
        remainder = "\n".join(lines[1:]).strip()
        if remainder:
            return remainder
    return text


def _excerpt(clause: Clause, limit: int = 240) -> str:
    flat = " ".join(clause.text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _locate(clauses: list[Clause], rule: Rule) -> list[Clause]:
    terms = rule.search_terms
    return [c for c in clauses if _any_match(c.text, terms) or _any_match(c.heading, terms)]


def _locate_mention(clauses: list[Clause], rule: Rule) -> list[Clause]:
    """Clauses that mention a rule's terms at all, negated or not."""
    terms = rule.search_terms
    return [c for c in clauses if _any_mention(c.text, terms) or _any_mention(c.heading, terms)]


def review_contract(contract_text: str, playbook: Playbook) -> ReviewResult:
    clauses = split_clauses(contract_text)
    findings: list[Finding] = []

    for rule in playbook.rules:
        located = _locate(clauses, rule)
        title = rule.title or rule.id
        if rule.kind == "required":
            satisfied = [c for c in located if _any_match(_body_text(c), rule.search_terms)]
            if not satisfied:
                negated = [
                    c for c in located
                    if _any_mention(_body_text(c), rule.search_terms)
                    and not _any_match(_body_text(c), rule.search_terms)
                ]
                if negated:
                    target = negated[0]
                    findings.append(Finding(
                        rule_id=rule.id, kind=rule.kind, severity=rule.severity, status="missing",
                        topic=rule.topic, clause_index=target.index, clause_heading=target.heading,
                        clause_number=target.number,
                        message=(
                            f"Required clause missing: {title}. The only mention in clause "
                            f"'{target.heading}' is negated, and a negated mention does not "
                            f"satisfy this requirement."
                        ),
                        rationale=rule.rationale, excerpt=_excerpt(target), fallback=rule.fallback,
                    ))
                else:
                    findings.append(Finding(
                        rule_id=rule.id, kind=rule.kind, severity=rule.severity, status="missing",
                        topic=rule.topic, message=f"Required clause missing: {title}.",
                        rationale=rule.rationale, fallback=rule.fallback,
                    ))
            elif rule.must_contain:
                target = satisfied[0]
                missing = [term for term in rule.must_contain if not _matches(_body_text(target), term)]
                if missing:
                    findings.append(Finding(
                        rule_id=rule.id, kind=rule.kind, severity=rule.severity, status="incomplete",
                        topic=rule.topic, clause_index=target.index, clause_heading=target.heading,
                        clause_number=target.number,
                        message=f"Clause '{target.heading}' is present but missing required element(s): {', '.join(missing)}.",
                        rationale=rule.rationale, excerpt=_excerpt(target), fallback=rule.fallback,
                    ))
        elif rule.kind == "forbidden":
            for clause in located:
                # For forbidden rules, 'located' already means a hit.
                findings.append(Finding(
                    rule_id=rule.id, kind=rule.kind, severity=rule.severity, status="forbidden",
                    topic=rule.topic, clause_index=clause.index, clause_heading=clause.heading,
                    clause_number=clause.number,
                    message=f"Forbidden language in clause '{clause.heading}': {title}.",
                    rationale=rule.rationale, excerpt=_excerpt(clause), fallback=rule.fallback,
                ))
        elif rule.kind == "fallback":
            if not located:
                mentioned = _locate_mention(clauses, rule)
                located_ids = {c.index for c in located}
                negated = [c for c in mentioned if c.index not in located_ids]
                if negated:
                    target = negated[0]
                    findings.append(Finding(
                        rule_id=rule.id, kind=rule.kind, severity=rule.severity, status="missing",
                        topic=rule.topic, clause_index=target.index, clause_heading=target.heading,
                        clause_number=target.number,
                        message=(
                            f"No clause found for fallback position: {title}. The only mention in "
                            f"clause '{target.heading}' is negated, and a negated mention does not "
                            f"count as this position."
                        ),
                        rationale=rule.rationale, excerpt=_excerpt(target), fallback=rule.fallback,
                    ))
                else:
                    findings.append(Finding(
                        rule_id=rule.id, kind=rule.kind, severity=rule.severity, status="missing",
                        topic=rule.topic, message=f"No clause found for fallback position: {title}.",
                        rationale=rule.rationale, fallback=rule.fallback,
                    ))
            else:
                target = located[0]
                body = _body_text(target)
                if rule.preferred and _any_match(body, rule.preferred):
                    pass  # Preferred position: no finding.
                elif rule.acceptable and (matched := _first_match(body, rule.acceptable)):
                    preferred_label = ", ".join(rule.preferred) if rule.preferred else "the preferred position"
                    findings.append(Finding(
                        rule_id=rule.id, kind=rule.kind, severity="low", status="fallback_acceptable",
                        topic=rule.topic, clause_index=target.index, clause_heading=target.heading,
                        clause_number=target.number,
                        message=(
                            f"Clause '{target.heading}' does not use the preferred position "
                            f"({preferred_label}) but uses an acceptable fallback position "
                            f"({matched}) for: {title}."
                        ),
                        rationale=rule.rationale, excerpt=_excerpt(target), fallback=rule.fallback,
                    ))
                else:
                    if rule.preferred or rule.acceptable:
                        message = (
                            f"Clause '{target.heading}' deviates from the approved position for: "
                            f"{title}. It matches neither the preferred position "
                            f"({', '.join(rule.preferred) or 'none stated'}) nor an acceptable "
                            f"fallback position ({', '.join(rule.acceptable) or 'none stated'})."
                        )
                    else:
                        message = f"Clause '{target.heading}' deviates from the approved position for: {title}."
                    findings.append(Finding(
                        rule_id=rule.id, kind=rule.kind, severity=rule.severity, status="deviation",
                        topic=rule.topic, clause_index=target.index, clause_heading=target.heading,
                        clause_number=target.number,
                        message=message,
                        rationale=rule.rationale, excerpt=_excerpt(target), fallback=rule.fallback,
                    ))
    return ReviewResult(
        playbook_id=playbook.id, playbook_name=playbook.name,
        findings=tuple(findings), clause_count=len(clauses),
        rules_checked=len(playbook.rules), clauses=tuple(clauses),
    )


def playbook_review(contract_text: str, playbook: Playbook) -> ReviewResult:
    return review_contract(contract_text, playbook)


def legal_playbook_review(contract_text: str, playbook) -> ReviewResult:
    """Behavior behind the ``legal_playbook_review`` tool.

    ``playbook`` may be a :class:`Playbook`, a path to a playbook
    file, or playbook text containing a ``## Rules`` section.
    Returns findings tied to clauses; changes nothing.
    """
    if isinstance(playbook, Playbook):
        pb = playbook
    elif isinstance(playbook, (str, Path)) and "\n" not in str(playbook) and Path(playbook).is_file():
        pb = load_playbook(playbook)
    elif isinstance(playbook, Path):
        pb = load_playbook(playbook)
    else:
        pb = parse_playbook(str(playbook))
    return review_contract(contract_text, pb)
