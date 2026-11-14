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
3. **Filing deadlines require dual entry.** Two different named
   confirmers are required when any signal marks a deadline as a filing
   deadline: the candidate text says file, filed, or filing; the caller
   passes the filing flag to `confirm_candidate` or
   `confirm_calculation`; or the rule data behind the deadline marks it
   as a filing rule. A signal can only raise the requirement, never
   lower it, on either creation path.
4. **Calculation shows the rule and the arithmetic.**
   `calculate` loads versioned rule data files from
   `src/hermes_legal/data/rules/` — each rule carries its citation,
   source, and version date — and returns every step: the trigger day
   excluded, the day count, any weekend or federal-holiday roll, and any
   added days for the service method. A check that changes nothing is
   stated too: when the last day needs no roll, or a rule carries no
   additional-time rule, the steps say so instead of staying silent.
   The federal holidays the counting rules roll past are data, not
   code: `federal-holidays.json` in the same directory holds the
   standard federal holiday list (calendar data from 5 U.S.C.
   section 6103, not a legal interpretation), and
   `federal_holidays(year)` is built from it.
5. **Export is .ics, confirmed rows only.** `export_ics` writes an
   RFC 5545 calendar containing only deadlines a human confirmed;
   unconfirmed rows never reach a calendar.
6. **Connected calendars get a payload.** `export_calendar_events`
   and `deadline_to_calendar_event` build the event payload a calendar
   connector would send for each confirmed deadline: an all-day event
   whose description carries the rule source, the stored calculation
   steps, and the verify warning, under the same calendar identity the
   .ics export uses. Unconfirmed rows are skipped in the list form and
   refused in the single-event form. Live calendar sync — actually
   sending the payload to a calendar service — is not built; it needs
   a connector and a connected account, which live outside the
   deadlines module.

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
and Rule 6(d) adds three days, exactly. Two further worked examples in
`tests/test_deadlines_remainders.py` are calculated by hand in that
file's header and reproduced step by step: a roll chain across a
Saturday, a Sunday, and Memorial Day before Rule 6(d) adds its days,
and a case where the days Rule 6(d) adds land on a Saturday and roll
again to Monday.

## Lawyer confirmation still open

One computation depends on a reading a lawyer has not yet confirmed,
and that confirmation is catduck's to give, not something the code can
settle: the answer-after-service rule carries no additional-time rule
in its data file, on the reading that Rule 6(d) reaches service under
Rule 5 and a summons and complaint are served under Rule 4. If that
reading changed, that rule's computed dates could change with it. The
rule data's correctness as a whole is under the same lawyer review.
Until then, treat every computed date as the warning below says.

## Warning that travels with every date

Every computed deadline carries this warning, in the calculation steps
and its dict form, in a candidate's dict form, in the record stored
for a confirmed deadline (candidate-confirmed rows included), in the
.ics description, and in the connected-calendar event payload:

> Verify against local rules, the scheduling order, and any stipulation
> before relying on this date. Court rules change, and local rules can
> change the period this calculation used.

The starter rule files cover a small set of Federal Rules of Civil
Procedure service and response examples. They are not a complete rule
library, and a period a court order sets for a specific case always wins
over a general rule file.
