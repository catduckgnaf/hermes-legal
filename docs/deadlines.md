# Deadlines

A miscalculated deadline is malpractice-grade, so Hermes Legal shows its
work and never confirms anything on its own.

## How it works

1. **Extraction returns candidates, and only candidates.**
   `hermes_legal.deadlines.extract_candidates` scans order and document
   text for explicit dates and for periods such as "within 30 days after
   service". It takes no database connection and writes nothing, so
   extraction alone can never create a deadline.
2. **A human confirms each deadline.** `confirm_candidate` and
   `confirm_calculation` are the only creation paths in the module, and
   both require a named human confirmer. The stored row records who
   confirmed it, when, and the excerpt or calculation behind it.
3. **Filing deadlines require dual entry.** A candidate whose text says
   file, filed, or filing needs two different named confirmers.
4. **Calculation shows the rule and the arithmetic.**
   `calculate` loads versioned rule data files from
   `src/hermes_legal/data/rules/` — each rule carries its citation,
   source, and version date — and returns every step: the trigger day
   excluded, the day count, any weekend or federal-holiday roll, and any
   added days for the service method.
5. **Export is .ics, confirmed rows only.** `export_ics` writes an
   RFC 5545 calendar containing only deadlines a human confirmed;
   unconfirmed rows never reach a calendar. Connected-calendar sync is
   not built yet; the .ics file is the export path today.

## Worked example

Answer after personal service, Federal Rule of Civil Procedure
12(a)(1)(A)(i), counted under Rule 6(a):

- Served Monday, March 2, 2026. Exclude the trigger day.
- Count 21 days: March 3 is day 1, and March 23 is day 21.
- March 23, 2026 is a Monday, so no roll applies, and personal service
  adds no days under Rule 6(d).
- Due: **Monday, March 23, 2026.**

The test suite (`tests/test_deadlines.py`) reproduces this hand
calculation, and a second one where service by mail lands on a Sunday
and Rule 6(d) adds three days, exactly.

## Warning that travels with every date

Every computed deadline carries this warning, in the calculation steps,
in the stored record, and in the .ics description:

> Verify against local rules, the scheduling order, and any stipulation
> before relying on this date. Court rules change, and local rules can
> change the period this calculation used.

The starter rule files cover a small set of Federal Rules of Civil
Procedure service and response examples. They are not a complete rule
library, and a period a court order sets for a specific case always wins
over a general rule file.
