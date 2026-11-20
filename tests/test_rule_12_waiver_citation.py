"""Rule 12(a)(1)(A)(ii) is the waiver answer, not Rule 12(a)(1)(B).

Checked against the Federal Rules of Civil Procedure pamphlet effective
December 1, 2024: 12(a)(1)(A)(ii) is 60 days after the waiver request was
sent (90 days if sent outside a judicial district of the United States).
12(a)(1)(B) is 21 days to answer a counterclaim or crossclaim.
"""
import datetime
import json

from hermes_legal import deadlines


def test_waiver_answer_cites_rule_12a1aii_and_keeps_the_60_day_period():
    rule = deadlines.get_rule("frcp-12a1aii-answer-after-waiver")
    assert rule["citation"] == "Fed. R. Civ. P. 12(a)(1)(A)(ii)"
    assert rule["period_days"] == 60
    assert "12(a)(1)(B)" not in rule["citation"]
    assert "waiver request was sent" in rule["summary"]
    # Sent March 2, 2026. The trigger day is excluded, so day 60 is May 1,
    # 2026, a Friday. The citation correction must not move the date.
    calc = deadlines.calculate(
        "frcp-12a1aii-answer-after-waiver", datetime.date(2026, 3, 2), "personal")
    assert calc.due_date == datetime.date(2026, 5, 1)
    assert "12(a)(1)(A)(ii)" in calc.rule_source
    rules = deadlines.load_rules()
    assert "frcp-12a1b-answer-after-waiver" not in rules
    payload = json.loads((deadlines.RULES_DIR / "frcp-service-response.json").read_text())
    assert payload["data_revision"] == 2
    assert payload["version_date"] == "2024-12-01"
