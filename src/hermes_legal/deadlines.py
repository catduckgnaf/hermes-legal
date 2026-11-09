"""Deadlines: candidate extraction, human confirmation, rule-based
calculation with the arithmetic shown, and .ics export.

Design rules, in code rather than only in prose:

- Extraction returns candidates and persists nothing. A candidate is never
  confirmed; only a human confirmation creates a row in ``deadlines``, and
  every creation path in this module requires a named confirmer.
- Filing deadlines require dual entry: two different named confirmers.
- Calculation is deterministic and stdlib-only. It loads versioned rule
  data files (each carrying its source and version date), and returns every
  arithmetic step plus the rule source, so a human can re-check the count
  by hand from the output alone.
- Every computed deadline carries VERIFY_WARNING. Local rules, court
  orders, and stipulations can change any period; this module never
  presents a computed date as verified law.
"""
import dataclasses
import datetime
import json
import pathlib
import re

VERIFY_WARNING = (
    "Verify against local rules, the scheduling order, and any stipulation "
    "before relying on this date. Court rules change, and local rules can "
    "change the period this calculation used."
)

RULES_DIR = pathlib.Path(__file__).parent / "data" / "rules"

_SERVICE_METHOD_ALIASES = {
    "personal": "personal",
    "hand": "personal",
    "electronic": "electronic",
    "email": "electronic",
    "e-service": "electronic",
    "mail": "mail",
    "leaving_with_clerk": "leaving_with_clerk",
    "clerk": "leaving_with_clerk",
    "other_consented": "other_consented",
}


# ---------------------------------------------------------------- rules data

def load_rules():
    """All rules from the versioned data files, keyed by rule id.

    Each returned rule dict carries ``source``, ``source_url``,
    ``version_date`` and ``ruleset`` copied from its data file, so a
    calculation can cite exactly where its numbers came from.
    """
    rules = {}
    for path in sorted(RULES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for rule in data.get("rules", []):
            entry = dict(rule)
            entry.setdefault("source", data.get("source", ""))
            entry.setdefault("source_url", data.get("source_url", ""))
            entry.setdefault("version_date", data.get("version_date", ""))
            entry.setdefault("ruleset", data.get("ruleset", ""))
            rules[entry["id"]] = entry
    return rules


def get_rule(rule_id, rules=None):
    rules = load_rules() if rules is None else rules
    if rule_id not in rules:
        raise ValueError(f"unknown rule id: {rule_id}")
    return rules[rule_id]


def rule_source_text(rule):
    return (f"{rule['citation']} — {rule['ruleset']}; source: {rule['source']} "
            f"({rule['source_url']}); version date {rule['version_date']}")


# ------------------------------------------------------------- calendar math

def _nth_weekday(year, month, weekday, n):
    first = datetime.date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + datetime.timedelta(days=shift + 7 * (n - 1))


def _last_weekday(year, month, weekday):
    if month == 12:
        last = datetime.date(year, 12, 31)
    else:
        last = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
    return last - datetime.timedelta(days=(last.weekday() - weekday) % 7)


def federal_holidays(year):
    """United States federal holidays for ``year`` (5 U.S.C. section 6103),
    as a dict of date -> name. Observed-day shifting for holidays that fall
    on a weekend is not applied; VERIFY_WARNING covers that check.
    """
    mon, thu = 0, 3
    return {
        datetime.date(year, 1, 1): "New Year's Day",
        _nth_weekday(year, 1, mon, 3): "Birthday of Martin Luther King, Jr.",
        _nth_weekday(year, 2, mon, 3): "Washington's Birthday",
        _last_weekday(year, 5, mon): "Memorial Day",
        datetime.date(year, 6, 19): "Juneteenth National Independence Day",
        datetime.date(year, 7, 4): "Independence Day",
        _nth_weekday(year, 9, mon, 1): "Labor Day",
        _nth_weekday(year, 10, mon, 2): "Columbus Day",
        datetime.date(year, 11, 11): "Veterans Day",
        _nth_weekday(year, 11, thu, 4): "Thanksgiving Day",
        datetime.date(year, 12, 25): "Christmas Day",
    }


def _non_business_reason(day, holidays):
    if day.weekday() == 5:
        return "a Saturday"
    if day.weekday() == 6:
        return "a Sunday"
    if day in holidays:
        return f"the federal holiday {holidays[day]}"
    return None


# --------------------------------------------------------------- calculation

@dataclasses.dataclass(frozen=True)
class Calculation:
    rule_id: str
    citation: str
    rule_source: str
    trigger_date: datetime.date
    due_date: datetime.date
    period_days: int
    service_method: str
    steps: tuple
    warning: str = VERIFY_WARNING
    is_filing: bool = False

    def to_dict(self):
        return {
            "rule_id": self.rule_id,
            "citation": self.citation,
            "rule_source": self.rule_source,
            "trigger_date": self.trigger_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "period_days": self.period_days,
            "service_method": self.service_method,
            "steps": list(self.steps),
            "warning": self.warning,
            "is_filing": self.is_filing,
        }


def _roll_forward(day, holidays, steps, label):
    reason = _non_business_reason(day, holidays)
    while reason is not None:
        nxt = day + datetime.timedelta(days=1)
        steps.append(
            f"{label}: {day.isoformat()} ({day.strftime('%A')}) is {reason}, "
            f"so the period continues to {nxt.isoformat()} ({nxt.strftime('%A')}).")
        day = nxt
        reason = _non_business_reason(day, holidays)
    return day


def calculate(rule_id, trigger_date, service_method="personal",
              holidays=None, rules=None):
    """Compute a deadline, returning every arithmetic step.

    Counting follows the counting rule the data file names (for the FRCP
    examples, Rule 6(a)): exclude the trigger day, count every day
    including intermediate weekends and holidays, and roll the last day
    forward when it lands on a weekend or legal holiday. When the rule
    carries an additional-time rule (Rule 6(d) in the FRCP examples) and
    the service method matches, the extra days are added after the period
    would otherwise expire, and the new last day is rolled forward again.
    """
    if isinstance(trigger_date, str):
        trigger_date = datetime.date.fromisoformat(trigger_date)
    method = _SERVICE_METHOD_ALIASES.get(str(service_method).strip().lower())
    if method is None:
        raise ValueError(f"unknown service method: {service_method}")
    rule = get_rule(rule_id, rules=rules)
    if rule.get("period_days") is None:
        raise ValueError(f"rule {rule_id} states no period in days; "
                         "it cannot be calculated on its own")
    period = int(rule["period_days"])
    if holidays is None:
        years = {trigger_date.year, (trigger_date + datetime.timedelta(days=period + 10)).year}
        holidays = {}
        for year in years:
            holidays.update(federal_holidays(year))
    counting_id = rule.get("counting_rule_id", "frcp-6a")
    counting = get_rule(counting_id, rules=rules) if counting_id else {}
    steps = []
    steps.append(
        f"Rule: {rule_source_text(rule)}. Period: {period} days after "
        f"{rule['trigger']}.")
    steps.append(
        f"Counting rule: {counting.get('citation', counting_id)} — exclude "
        f"the trigger day, count every day including intermediate Saturdays, "
        f"Sundays, and legal holidays, and roll the last day forward when it "
        f"is a Saturday, Sunday, or legal holiday.")
    steps.append(
        f"Step 1: exclude the trigger day, {trigger_date.isoformat()} "
        f"({trigger_date.strftime('%A')}). Counting starts "
        f"{(trigger_date + datetime.timedelta(days=1)).isoformat()}.")
    last = trigger_date + datetime.timedelta(days=period)
    steps.append(
        f"Step 2: count {period} days from the day after the trigger day: "
        f"{trigger_date.isoformat()} + {period} days = {last.isoformat()} "
        f"({last.strftime('%A')}). That is day {period} of the period.")
    last = _roll_forward(last, holidays, steps,
                         "Step 3 (last-day check under the counting rule)")
    steps.append(f"Step 3 result: the period would otherwise expire on "
                 f"{last.isoformat()} ({last.strftime('%A')}).")
    extra_id = rule.get("additional_time_rule_id")
    if extra_id:
        extra = get_rule(extra_id, rules=rules)
        applies = method in extra.get("applies_to_service_methods", [])
        if applies:
            added = int(extra["additional_days"])
            new_last = last + datetime.timedelta(days=added)
            steps.append(
                f"Step 4: {extra['citation']} adds {added} days because "
                f"service was by {method}: {last.isoformat()} + {added} "
                f"days = {new_last.isoformat()} ({new_last.strftime('%A')}).")
            last = _roll_forward(new_last, holidays, steps,
                                 "Step 5 (last-day check after the added days)")
        else:
            steps.append(
                f"Step 4: {extra['citation']} does not apply here: service "
                f"was by {method}, not one of "
                f"{', '.join(extra.get('applies_to_service_methods', []))}. "
                f"No days are added.")
    steps.append(f"Result: due {last.isoformat()} ({last.strftime('%A')}).")
    steps.append(f"Warning: {VERIFY_WARNING}")
    return Calculation(
        rule_id=rule["id"], citation=rule["citation"],
        rule_source=rule_source_text(rule), trigger_date=trigger_date,
        due_date=last, period_days=period, service_method=method,
        steps=tuple(steps), is_filing=bool(rule.get("is_filing")))


# ---------------------------------------------------------------- extraction

_MONTHS = {name: i for i, name in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}
_MONTHS.update({name[:3]: num for name, num in list(_MONTHS.items())})
_MONTHS["sept"] = 9

_EXPLICIT_PATTERNS = [
    re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s+(\d{4})\b"),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"),
]
_RELATIVE_RE = re.compile(
    r"\b(?:within|no\s+later\s+than|not\s+later\s+than|not\s+more\s+than)\s+"
    r"(?:[a-z-]+\s+\()?(\d{1,3})\)?\s+(?:calendar\s+|court\s+|business\s+)?days?\s+"
    r"(?:after|of|from|following)\s+([^.;\n]{3,80})",
    re.IGNORECASE)
_FILING_RE = re.compile(r"\b(file|filed|filing)\b", re.IGNORECASE)

# Trigger phrases in orders and discovery papers -> starter rule ids.
_RULE_HINTS = [
    (re.compile(r"answer.*complaint|summons and complaint", re.I), "frcp-12a1ai-answer-after-service"),
    (re.compile(r"interrogator", re.I), "frcp-33b2-interrogatory-answers"),
    (re.compile(r"requests? for production|documents? .*request", re.I), "frcp-34b2a-document-request-response"),
    (re.compile(r"requests? for admission", re.I), "frcp-36a3-admission-response"),
    (re.compile(r"new trial", re.I), "frcp-59b-new-trial-motion"),
]


@dataclasses.dataclass(frozen=True)
class Candidate:
    excerpt: str
    kind: str                      # "explicit_date" | "relative_period"
    raw: str
    due_date: datetime.date | None = None
    period_days: int | None = None
    trigger_text: str = ""
    rule_id: str | None = None
    is_filing: bool = False
    confirmed: bool = False        # extraction can never confirm

    def to_dict(self):
        data = dataclasses.asdict(self)
        if self.due_date is not None:
            data["due_date"] = self.due_date.isoformat()
        return data


def _sentences(text):
    return re.split(r"(?<=[.;])\s+|\n+", text)


def _parse_explicit(match, pattern_index):
    try:
        if pattern_index == 0:
            month = _MONTHS[match.group(1).lower().rstrip(".")]
            return datetime.date(int(match.group(3)), month, int(match.group(2)))
        if pattern_index == 1:
            return datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return datetime.date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
    except (KeyError, ValueError):
        return None


def extract_candidates(text):
    """Return candidate dates and periods found in ``text``.

    Pure and side-effect free: this function takes no database connection
    and writes nothing, so extraction alone can never create a deadline.
    Every candidate comes back with ``confirmed=False``.
    """
    candidates = []
    seen = set()
    for sentence in _sentences(text or ""):
        excerpt = " ".join(sentence.split())[:300]
        if not excerpt:
            continue
        is_filing = bool(_FILING_RE.search(sentence))
        rule_id = next((rid for pat, rid in _RULE_HINTS if pat.search(sentence)), None)
        for idx, pattern in enumerate(_EXPLICIT_PATTERNS):
            for match in pattern.finditer(sentence):
                due = _parse_explicit(match, idx)
                if due is None:
                    continue
                key = ("explicit_date", match.group(0), due)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(Candidate(
                    excerpt=excerpt, kind="explicit_date", raw=match.group(0),
                    due_date=due, rule_id=rule_id, is_filing=is_filing))
        for match in _RELATIVE_RE.finditer(sentence):
            key = ("relative_period", match.group(0))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(Candidate(
                excerpt=excerpt, kind="relative_period", raw=match.group(0),
                period_days=int(match.group(1)),
                trigger_text=match.group(2).strip(),
                rule_id=rule_id, is_filing=is_filing))
    return candidates


# ------------------------------------------------------- confirmation / store

_EXTRA_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'confirmed'",
    "kind": "TEXT NOT NULL DEFAULT ''",
    "confirmed_by": "TEXT NOT NULL DEFAULT ''",
    "second_confirmer": "TEXT NOT NULL DEFAULT ''",
    "confirmed_at": "TEXT NOT NULL DEFAULT ''",
    "source_excerpt": "TEXT NOT NULL DEFAULT ''",
    "rule_id": "TEXT NOT NULL DEFAULT ''",
    "calculation_json": "TEXT NOT NULL DEFAULT ''",
}


def ensure_deadline_columns(conn):
    """Add the confirmation columns to an existing deadlines table.

    The base schema in db.py already carries these columns for new files;
    databases created before they existed gain them here, with existing
    rows left untouched (their ``verified`` value still governs them).
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(deadlines)")}
    for name, decl in _EXTRA_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE deadlines ADD COLUMN {name} {decl}")
    conn.commit()


def _check_confirmers(is_filing, confirmed_by, second_confirmer):
    if not (confirmed_by or "").strip():
        raise ValueError("a named human confirmer is required; "
                         "extraction alone never confirms a deadline")
    if is_filing:
        if not (second_confirmer or "").strip():
            raise ValueError("filing deadlines require dual entry: "
                             "a second, different human confirmer is required")
        if second_confirmer.strip() == confirmed_by.strip():
            raise ValueError("filing deadlines require dual entry: "
                             "the second confirmer must differ from the first")


def _insert(conn, matter_id, due_at, title, rule_source, kind, confirmed_by,
            second_confirmer, source_excerpt, rule_id, calculation_json):
    ensure_deadline_columns(conn)
    cur = conn.execute(
        "INSERT INTO deadlines (matter_id, due_at, title, rule_source, "
        "verified, status, kind, confirmed_by, second_confirmer, "
        "confirmed_at, source_excerpt, rule_id, calculation_json) "
        "VALUES (?, ?, ?, ?, 1, 'confirmed', ?, ?, ?, datetime('now'), ?, ?, ?)",
        (matter_id, due_at, title, rule_source, kind, confirmed_by.strip(),
         (second_confirmer or "").strip(), source_excerpt, rule_id or "",
         calculation_json))
    conn.commit()
    return cur.lastrowid


def confirm_candidate(conn, matter_id, candidate, title, confirmed_by,
                      second_confirmer=None, due_date=None):
    """Create a confirmed deadline from a candidate. The only path by
    which an extracted candidate becomes a deadline, and it requires a
    named human confirmer (two, for filing deadlines).
    """
    due = due_date or candidate.due_date
    if due is None:
        raise ValueError("this candidate states a period, not a date; "
                         "calculate it first or supply the confirmed due date")
    _check_confirmers(candidate.is_filing, confirmed_by, second_confirmer)
    if isinstance(due, datetime.date):
        due = due.isoformat()
    rule_source = ""
    if candidate.rule_id:
        try:
            rule_source = rule_source_text(get_rule(candidate.rule_id))
        except ValueError:
            rule_source = ""
    return _insert(conn, matter_id, due, title, rule_source,
                   candidate.kind, confirmed_by, second_confirmer,
                   candidate.excerpt, candidate.rule_id, "")


def confirm_calculation(conn, matter_id, calculation, title, confirmed_by,
                        second_confirmer=None, is_filing=False):
    """Persist a calculated deadline after human confirmation. The stored
    row keeps the citation, the rule source, and the full step list, so the
    arithmetic stays auditable in the database.
    """
    # The rule data can only raise this requirement, never lower it.
    _check_confirmers(is_filing or calculation.is_filing, confirmed_by, second_confirmer)
    return _insert(conn, matter_id, calculation.due_date.isoformat(), title,
                   calculation.rule_source, "calculated", confirmed_by,
                   second_confirmer, "", calculation.rule_id,
                   json.dumps(calculation.to_dict()))


def list_deadlines(conn, matter_id):
    ensure_deadline_columns(conn)
    conn.row_factory = _dict_row
    try:
        return conn.execute(
            "SELECT * FROM deadlines WHERE matter_id=? ORDER BY due_at, id",
            (matter_id,)).fetchall()
    finally:
        conn.row_factory = None


def _dict_row(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


# ------------------------------------------------------------------ .ics out

def _ics_escape(value):
    return (str(value).replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def deadlines_to_ics(deadlines, now=None):
    """RFC 5545 calendar text for confirmed deadlines only.

    Rows with ``verified`` falsy or a status other than ``confirmed`` are
    skipped: an unconfirmed candidate never reaches a calendar.
    ``now`` is injectable so tests get a stable DTSTAMP.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//Hermes Legal//Deadlines//EN", "CALSCALE:GREGORIAN"]
    for row in deadlines:
        if not row.get("verified"):
            continue
        if row.get("status") not in (None, "", "confirmed"):
            continue
        due = datetime.date.fromisoformat(str(row["due_at"])[:10])
        lines += [
            "BEGIN:VEVENT",
            f"UID:deadline-{row.get('id', due.isoformat())}@hermes-legal.local",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{due.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(due + datetime.timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_ics_escape(row.get('title', 'Deadline'))}",
            "DESCRIPTION:" + _ics_escape(
                f"Rule source: {row.get('rule_source', '')}\n{VERIFY_WARNING}"),
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def export_ics(conn, matter_id, now=None):
    return deadlines_to_ics(list_deadlines(conn, matter_id), now=now)
